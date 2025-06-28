# adam.py - Diagnóstico de Rede Interativo para Técnicos de Campo
# Desenvolvido para ISPs, redes locais e ambientes Linux com foco em UX de terminal

import os
import sys
import subprocess
import json
import time
import datetime
import socket
import threading
import re
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()
LOG_DIR = "log_rede"
os.makedirs(LOG_DIR, exist_ok=True)

# ========== UTILITÁRIOS ==========

def run_command(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.SubprocessError as e:
        return "", str(e)
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        return f"[Erro]\n{e.output}"

def run_command_live(cmd):
    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = ""
        for line in process.stdout:
            console.print(line.rstrip())
            output += line
        process.wait()
        return output
    except Exception as e:
        return f"[Erro ao executar live]: {e}"

def comando_existe(cmd):
    return subprocess.call(f"type {cmd}", shell=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0

def save_log(title, content):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    txt_file = os.path.join(LOG_DIR, f"{title}_{timestamp}.txt")
    json_file = os.path.join(LOG_DIR, f"{title}_{timestamp}.json")
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(content)
    json_data = {"title": title, "timestamp": timestamp, "output": content}
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2)
    console.print(f"\n✅ Log salvo em:\n[green]- {txt_file}\n- {json_file}[/green]")

def post_test_menu(result, titulo=None):
    while True:
        console.print("\n[bold green]1 - Salvar log   |   2 - Voltar ao menu[/bold green]")
        opc = input("Escolha: ").strip()
        if opc == '1':
            save_log(titulo or "resultado", result)
        elif opc == '2':
            return
        else:
            console.print("[red]Opção inválida.[/red]")

# ========== FUNÇÕES BÁSICAS ==========

def diagnostico_interfaces():
    output, _ = run_command("ip -o link show | awk -F': ' '{print $2}'")
    interfaces = [i for i in output.splitlines() if not any(x in i for x in ["lo", "vir", "docker", "tun", "br-", "veth"])]
    result = "\n".join(interfaces)
    console.print(Panel(result, title="Interfaces Ativas", style="cyan"))
    post_test_menu(result, "interfaces_ativas")

def diagnostico_ip_rota():
    result, _ = run_command("ip a") + "\n\n" + run_command("ip r")
    console.print(Panel(result, title="IP e Rota", style="cyan"))
    post_test_menu(result, "ip_rota")

def get_gateway():
    route, _ = run_command("ip r")
    for line in route.splitlines():
        if line.startswith("default"):
            return line.split()[2]
    return None

def diagnostico_ping_gateway():
    gateway = get_gateway()
    if not gateway:
        result = "Gateway não encontrado."
        console.print(Panel(result, title="Ping Gateway", style="red"))
        post_test_menu(result, "ping_gateway")
        return

    raw, _ = run_command(f"ping -c 10 {gateway}")
    perda_match = re.search(r"(\d+)% packet loss", raw)
    perda_pct = int(perda_match.group(1)) if perda_match else 0

    lat_match = re.findall(r'time=(\d+\.\d+)', raw)
    if lat_match:
        tempos = [float(x) for x in lat_match]
        media = sum(tempos) / len(tempos)
        jitter = max(abs(tempos[i] - tempos[i-1]) for i in range(1, len(tempos)))
    else:
        media, jitter = 0, 0

    status = []
    if perda_pct > 20:
        status.append("🔴 Alta perda de pacotes")
    elif perda_pct > 5:
        status.append("🟡 Perda moderada")

    if media > 150:
        status.append("🔴 Latência alta")
    elif media > 80:
        status.append("🟡 Latência acima do ideal")

    if jitter > 20:
        status.append("🟡 Jitter elevado")

    if not status:
        classificacao = "✅ Conexão com o gateway estável"
    else:
        classificacao = "\n".join(status)

    result = f"""\
Gateway: {gateway}
Latência média: {media:.2f} ms
Jitter estimado: {jitter:.2f} ms
Perda de pacotes: {perda_pct}%

{classificacao}
"""
    console.print(Panel(result.strip(), title="Diagnóstico - Gateway", style="cyan"))
    post_test_menu(result.strip(), "ping_gateway")

def diagnostico_ping_custom():
    ip = input("Digite o IP ou domínio de destino (ex: 8.8.8.8): ").strip()
    count = input("Quantos pacotes deseja enviar? (ex: 10): ").strip()
    if not count.isdigit(): count = "10"
    result = run_command_live(f"ping -c {count} {ip}")
    console.print(Panel(result, title=f"Ping para {ip}", style="cyan"))
    post_test_menu(result, f"ping_{ip.replace('.', '_')}")

def diagnostico_dns():
    dig, _ = run_command("dig google.com +short") if comando_existe("dig") else "Comando 'dig' não encontrado."
    host, _ = run_command("host google.com") if comando_existe("host") else "Comando 'host' não encontrado."
    result = f"dig google.com:\n{dig}\n\nhost google.com:\n{host}"
    console.print(Panel(result, title="Testes de DNS", style="cyan"))
    post_test_menu(result, "dns")

def diagnostico_portas():
    host = input("Informe o IP ou host (ex: 8.8.8.8): ").strip()
    portas_str = input("Informe as portas separadas por vírgula (ex: 80,443,22): ").strip()
    try:
        portas = [int(p.strip()) for p in portas_str.split(',')]
    except:
        console.print("[red]Portas inválidas.[/red]")
        return
    resultados = {}
    for port in portas:
        try:
            with socket.create_connection((host, port), timeout=2):
                resultados[port] = "Aberta"
        except Exception:
            resultados[port] = "Fechada"
    result = f"Host: {host}\n" + "\n".join([f"Porta {p}: {s}" for p, s in resultados.items()])
    console.print(Panel(result, title="Teste de Portas", style="cyan"))
    post_test_menu(result, "portas_custom")

def diagnostico_ip_publico():
    result, _ = run_command("curl -s ifconfig.me")
    console.print(Panel(result, title="IP Público", style="cyan"))
    post_test_menu(result, "ip_publico")

def diagnostico_dhcp():
    result, _ = run_command("journalctl -b --since '10 minutes ago' -g DHCP")
    console.print(Panel(result, title="Logs de DHCP", style="cyan"))
    post_test_menu(result, "dhcp")

def diagnostico_latency_jitter():
    console.rule("[bold blue]Diagnóstico de Latência e Jitter[/bold blue]")
    raw, err = run_command("ping -c 10 8.8.8.8")

    if not raw:
        result = f"O comando ping não retornou saída.\nErro:\n{err}"
        console.print(Panel(result, title="Latência e Jitter", style="red"))
        post_test_menu(result, "latencia_jitter")
        return

    times = re.findall(r'time=(\d+\.\d+)', raw)
    if not times:
        result = f"Não foi possível calcular latência/jitter.\n\nSaída bruta:\n{raw}"
        console.print(Panel(result, title="Latência e Jitter", style="red"))
        post_test_menu(result, "latencia_jitter")
        return

    times = [float(t) for t in times]
    media = sum(times) / len(times)
    jitter = max(abs(times[i] - times[i-1]) for i in range(1, len(times)))
    perda_match = re.search(r'(\d+)% packet loss', raw)
    perda_pct = int(perda_match.group(1)) if perda_match else 0

    status = []
    causas = []
    solucoes = []

    if perda_pct > 10:
        status.append("🔴 Perda alta de pacotes")
        causas.append("Sinal fraco, interferência ou instabilidade na rede")
        solucoes.append("Verificar sinal Wi-Fi ou testar via cabo")

    if jitter > 30:
        status.append("🔴 Jitter alto")
        causas.append("Bufferbloat ou congestionamento")
        solucoes.append("Ativar QoS ou testar sem outros dispositivos na rede")
    elif jitter > 10:
        status.append("🟡 Jitter moderado")

    if media > 150:
        status.append("🔴 Latência muito alta")
        causas.append("Conexão lenta ou rota internacional")
        solucoes.append("Testar DNS, trocar horário ou checar provedor")
    elif media > 80:
        status.append("🟡 Latência acima do ideal")

    if not status:
        classificacao = "✅ Rede excelente"
    elif "🔴" not in "".join(status):
        classificacao = "🟡 Rede boa, com oscilações"
    elif status.count("🔴") <= 2:
        classificacao = "🟠 Rede instável"
    else:
        classificacao = "🔴 Rede ruim"

    result = f"""
[bold cyan]Diagnóstico de Latência e Jitter[/bold cyan]

[bold]Latência média:[/bold] {media:.2f} ms
[bold]Jitter estimado:[/bold] {jitter:.2f} ms
[bold]Perda de pacotes:[/bold] {perda_pct} %

[bold magenta]Classificação:[/bold magenta] {classificacao}
"""

    if status:
        result += "\n[bold red]Problemas identificados:[/bold red]\n- " + "\n- ".join(status)
    if causas:
        result += "\n\n[bold yellow]Possíveis causas:[/bold yellow]\n- " + "\n- ".join(causas)
    if solucoes:
        result += "\n\n[bold green]Sugestões de solução:[/bold green]\n- " + "\n- ".join(solucoes)

    console.print(Panel(result.strip(), title="Latência e Jitter - Análise", style="cyan"))
    post_test_menu(result.strip(), "latencia_jitter")

# ========== FUNÇÕES AVANÇADAS ==========

def diagnostico_speedtest():
    if not comando_existe("speedtest"):
        result = "SpeedTest CLI não instalado.\nInstale com:\ncurl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash\nsudo apt install speedtest"
        console.print(Panel(result, title="SpeedTest - Erro", style="red"))
        post_test_menu(result, "speedtest_nao_instalado")
        return

    console.print("[cyan]Executando SpeedTest CLI oficial...[/cyan]")
    output, _ = run_command("speedtest --accept-license --accept-gdpr --format=json")

    try:
        data = json.loads(output)
        ping = data["ping"]["latency"]
        jitter = data["ping"].get("jitter", 0)
        download = data["download"]["bandwidth"] * 8 / 1_000_000  # em Mbps
        upload = data["upload"]["bandwidth"] * 8 / 1_000_000
        loss = data.get("packetLoss", 0)
        url = data.get("result", {}).get("url", "")
    except Exception as e:
        console.print(Panel(f"[red]Erro ao interpretar resultado JSON:[/red] {e}", title="Erro SpeedTest"))
        post_test_menu(output, "erro_speedtest_parse")
        return

    # Diagnóstico
    status = []
    causas = []
    solucoes = []

    # Classificação de qualidade
    if loss > 2:
        status.append("🔴 Perda alta")
        causas.append("Possível instabilidade física (Wi-Fi fraco, ruído, cabo danificado)")
        solucoes.append("Trocar interface, testar com cabo, evitar obstáculos")
    elif loss > 0:
        status.append("🟡 Perda moderada")
        causas.append("Flutuações ocasionais, possível interferência")
        solucoes.append("Reiniciar modem, testar com outro roteador")

    if jitter > 30:
        status.append("🔴 Jitter alto")
        causas.append("Bufferbloat ou instabilidade durante tráfego")
        solucoes.append("Ativar QoS, substituir roteador")
    elif jitter > 10:
        status.append("🟡 Jitter moderado")

    if ping > 150:
        status.append("🔴 Latência alta")
        causas.append("Rota internacional ou rede congestionada")
        solucoes.append("Testar em outro horário, trocar DNS")
    elif ping > 50:
        status.append("🟡 Latência acima do ideal")

    if download < 10 or upload < 3:
        status.append("🔴 Banda baixa")
        causas.append("Plano limitado, tráfego alto, gargalo no provedor")
        solucoes.append("Verificar contrato, uso compartilhado ou horários de pico")

    if not status:
        classificacao = "✅ Rede excelente"
    elif "🔴" not in "".join(status):
        classificacao = "🟡 Rede boa, com pontos a observar"
    elif status.count("🔴") <= 2:
        classificacao = "🟠 Rede instável"
    else:
        classificacao = "🔴 Rede ruim"

    result = f"""
[bold cyan]SpeedTest CLI - Diagnóstico[/bold cyan]

[bold]Servidor:[/bold] {data['server']['name']} ({data['server']['location']})
[bold]Operadora:[/bold] {data['isp']}

[bold]Latência:[/bold] {ping:.2f} ms
[bold]Jitter:[/bold] {jitter:.2f} ms
[bold]Download:[/bold] {download:.2f} Mbps
[bold]Upload:[/bold] {upload:.2f} Mbps
[bold]Perda de Pacotes:[/bold] {loss}%
[bold]Resultado:[/bold] {url}

[bold magenta]Classificação:[/bold magenta] {classificacao}
"""

    if status:
        result += "\n[bold red]Problemas identificados:[/bold red]\n- " + "\n- ".join(status)
    if causas:
        result += "\n\n[bold yellow]Possíveis causas:[/bold yellow]\n- " + "\n- ".join(causas)
    if solucoes:
        result += "\n\n[bold green]Sugestões de solução:[/bold green]\n- " + "\n- ".join(solucoes)

    console.print(Panel(result.strip(), title="SpeedTest - Análise Automática", style="magenta"))
    post_test_menu(result.strip(), "speedtest_diagnostico")

def diagnostico_rota_interface():
    interfaces, _ = run_command("ip -o link show | awk -F': ' '{print $2}'").splitlines()
    interfaces = [i for i in interfaces if not i.startswith("lo")]
    console.print("[bold cyan]Interfaces disponíveis:[/bold cyan]")
    for idx, iface in enumerate(interfaces):
        console.print(f"[{idx}] {iface}")
    escolha = input("Escolha a interface (número): ").strip()
    try:
        iface = interfaces[int(escolha)]
        result = run_command_live(f"ping -I {iface} -c 5 8.8.8.8")
    except:
        result = "Erro ao selecionar interface."
    console.print(Panel(result, title="Ping por Interface", style="magenta"))
    post_test_menu(result, "ping_interface")

def diagnostico_captive():
    result, _ = run_command("curl -I http://clients3.google.com/generate_204")
    if "204" in result:
        status = "✅ Sem captive portal"
    else:
        status = "⚠️ Possível redirecionamento ou bloqueio"
    final = f"{result}\\n\\nDiagnóstico: {status}"
    console.print(Panel(final, title="Captive Portal", style="magenta"))
    post_test_menu(final, "captive_portal")

def diagnostico_dns_bloqueado():
    resultado = ""
    for tipo in ["tcp", "udp"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if tipo == "tcp" else socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 53))
            resultado += f"Porta 53 {tipo.upper()}: Acessível\\n"
        except:
            resultado += f"Porta 53 {tipo.upper()}: Bloqueada\\n"
        finally:
            s.close()
    console.print(Panel(resultado, title="Bloqueio de DNS (porta 53)", style="magenta"))
    post_test_menu(resultado, "dns_block")

def diagnostico_mtu():
    tamanho = 1472
    while tamanho > 1000:
        resultado, _ = run_command(f"ping -c 1 -s {tamanho} -M do 8.8.8.8")
        if "Frag needed" in resultado or "Message too long" in resultado or "100% packet loss" in resultado:
            tamanho -= 10
        else:
            break
    final = f"MTU máximo sem fragmentação estimado: {tamanho + 28} bytes (incluindo cabeçalhos IP/ICMP)"
    console.print(Panel(final, title="Teste de MTU", style="magenta"))
    post_test_menu(final, "mtu")

def diagnostico_multiplos_gateways():
    rotas, _ = run_command("ip r")
    linhas = [l for l in rotas.splitlines() if l.startswith("default")]
    resultado = "\\n".join(linhas)
    status = "✅ Apenas um gateway padrão" if len(linhas) == 1 else "⚠️ Múltiplos gateways detectados"
    final = f"{resultado}\\n\\nDiagnóstico: {status}"
    console.print(Panel(final, title="Verificação de múltiplos gateways", style="magenta"))
    post_test_menu(final, "multiplos_gateways")

def diagnostico_traceroute():
    destino = input("Digite o destino (IP ou domínio): ").strip() or "8.8.8.8"
    result = run_command_live(f"traceroute {destino}")
    console.print(Panel(result, title=f"Traceroute para {destino}", style="cyan"))
    post_test_menu(result, f"traceroute_{destino.replace('.', '_')}")

def diagnostico_mtr():
    if not comando_existe("mtr"):
        result = "Comando 'mtr' não encontrado. Instale com: sudo apt install mtr"
    else:
        destino = input("Destino (ex: 8.8.8.8): ").strip() or "8.8.8.8"
        result = run_command_live(f"mtr --report --report-cycles 10 {destino}")
    console.print(Panel(result, title=f"MTR para {destino}", style="cyan"))
    post_test_menu(result, f"mtr_{destino.replace('.', '_')}")

def netdiscover_custom():
    console.rule("[bold blue]Netdiscover Customizado[/bold blue]")
    # Listar interfaces de rede disponíveis (não loopback)
    interfaces = []
    try:
        res = subprocess.run("ip -o link show | awk -F': ' '{print $2}'", shell=True, capture_output=True, text=True)
        interfaces = [i for i in res.stdout.splitlines() if i != 'lo']
    except Exception as e:
        console.print(f"[red]Erro ao listar interfaces: {e}[/red]")
        return

    if not interfaces:
        console.print("[red]Nenhuma interface de rede disponível encontrada.[/red]")
        return

    console.print("Interfaces disponíveis:")
    for idx, iface in enumerate(interfaces, 1):
        console.print(f"{idx}. {iface}")

    choice = Prompt.ask("Escolha o número da interface para escanear", choices=[str(i) for i in range(1, len(interfaces)+1)])
    iface = interfaces[int(choice)-1]

    use_range = Confirm.ask("Quer informar um range IP customizado para o escaneamento?")
    if use_range:
        ip_range = Prompt.ask("Informe o range IP (exemplo: 192.168.1.0/24)")
    else:
        ip_range = None

    console.print(f"Executando netdiscover na interface [green]{iface}[/green] com range: [cyan]{ip_range or 'padrão'}[/cyan]")

    # Montar comando netdiscover
    # Caso não tenha range, roda netdiscover em modo passivo na interface (ex: sudo netdiscover -i eth0 -p)
    # Se range informado, usa -r <range>
    if ip_range:
        cmd = f"sudo netdiscover -i {iface} -r {ip_range} -P -N"
    else:
        cmd = f"sudo netdiscover -i {iface} -P -N"

    # Executar netdiscover e capturar saída
    console.print("[yellow]Aguardando resultados... (Ctrl+C para parar)[/yellow]")
    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start_time = time.time()
        discoveries = []
        while True:
            line = process.stdout.readline()
            if not line:
                break
            # Filtrar linhas relevantes que contenham IP e MAC
            if any(c.isdigit() for c in line) and ":" in line:
                console.print(line.strip())
                discoveries.append(line.strip())
            # Limitar tempo para 30 segundos (opcional)
            if time.time() - start_time > 30:
                process.terminate()
                break
        log_data['netdiscover'] = discoveries
    except KeyboardInterrupt:
        process.terminate()
        console.print("\n[red]Interrompido pelo usuário.[/red]")
    except Exception as e:
        console.print(f"[red]Erro durante netdiscover: {e}[/red]")

# Essa função não ativa conexão automática nem salva configuração persistente no sistema
# Apenas configura IP na interface via comando ip addr add
# Salva localmente em arquivo para controle do técnico
def set_static_ip():
    console.rule("[bold blue]Configurar IP Estático na Interface Ethernet[/bold blue]")
    # Listar interfaces Ethernet disponíveis (exemplo: eth0, enp3s0...)
    try:
        res = subprocess.run("ip -o link show | awk -F': ' '{print $2}'", shell=True, capture_output=True, text=True)
        interfaces = [i for i in res.stdout.splitlines() if i.startswith('eth') or i.startswith('enp')]
    except Exception as e:
        console.print(f"[red]Erro ao listar interfaces Ethernet: {e}[/red]")
        return

    if not interfaces:
        console.print("[red]Nenhuma interface Ethernet detectada.[/red]")
        return

    console.print("Interfaces Ethernet disponíveis:")
    for idx, iface in enumerate(interfaces, 1):
        console.print(f"{idx}. {iface}")

    choice = Prompt.ask("Escolha a interface para configurar", choices=[str(i) for i in range(1, len(interfaces)+1)])
    iface = interfaces[int(choice)-1]

    ip_addr = Prompt.ask("Informe o IP estático (ex: 192.168.1.50)")
    netmask = Prompt.ask("Informe a máscara de rede (ex: 24 para 255.255.255.0)")
    gateway = Prompt.ask("Informe o gateway (ex: 192.168.1.1)")

    # Comandos para limpar IP atual e aplicar o novo
    # Remover IP antigo (caso exista)
    rm_cmd = f"sudo ip addr flush dev {iface}"
    add_cmd = f"sudo ip addr add {ip_addr}/{netmask} dev {iface}"
    gw_cmd = f"sudo ip route add default via {gateway} dev {iface}"

    console.print("[yellow]Aplicando configurações...[/yellow]")
    out, err, _ = run_command(rm_cmd)
    if err:
        console.print(f"[red]Erro ao limpar IP: {err}[/red]")
    out, err, _ = run_command(add_cmd)
    if err:
        console.print(f"[red]Erro ao configurar IP: {err}[/red]")
    out, err, _ = run_command(gw_cmd)
    if err and "File exists" not in err:
        console.print(f"[red]Erro ao configurar gateway: {err}[/red]")

    console.print(f"[green]IP estático configurado em {iface}: {ip_addr}/{netmask}, gateway {gateway}[/green]")

    # Salvar configuração localmente em arquivo json (lista IPs estáticos configurados)
    saved_configs = {}
    file_path = "static_ips_config.json"
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                saved_configs = json.load(f)
            except:
                saved_configs = {}

    saved_configs[iface] = {
        "ip": ip_addr,
        "netmask": netmask,
        "gateway": gateway,
        "timestamp": datetime.now().isoformat()
    }
    with open(file_path, 'w') as f:
        json.dump(saved_configs, f, indent=4)

    console.print(f"[cyan]Configuração salva localmente em {file_path}[/cyan]")
    log_data['static_ip'] = saved_configs

def test_download_speed():
    console.rule("[bold blue]Teste de Download - Análise de Velocidade[/bold blue]")

    urls = [("Hetzner 100MB", "https://nbg1-speed.hetzner.com/100MB.bin")]
    console.print("Escolha o arquivo para teste de download:")
    for idx, (name, url) in enumerate(urls, 1):
        console.print(f"{idx}. {name} - {url}")
    choice = Prompt.ask("Número da opção", choices=[str(i) for i in range(1, len(urls)+1)])
    name, url = urls[int(choice)-1]

    try:
        start = time.time()
        out, _ = run_command(f"curl -o /dev/null -s -w '%{{size_download}};%{{time_total}}' {url}")
        bytes_downloaded, time_taken = out.split(";")
        bytes_downloaded = int(bytes_downloaded)
        time_taken = float(time_taken)
        mbps = (bytes_downloaded * 8) / (time_taken * 1_000_000)
    except Exception as e:
        result = f"Erro no download: {e}"
        console.print(Panel(result, title="Erro no Teste de Download", style="red"))
        post_test_menu(result, "teste_download")
        return

    if mbps > 50:
        status = "✅ Excelente"
    elif mbps > 20:
        status = "🟡 Boa"
    elif mbps > 5:
        status = "🟠 Instável"
    else:
        status = "🔴 Ruim"

    result = f"""\
[bold cyan]Resultado do Teste de Download[/bold cyan]

Arquivo: {name}
URL: {url}

Tempo total: {time_taken:.2f} s
Bytes baixados: {bytes_downloaded} bytes
Velocidade média: {mbps:.2f} Mbps

Classificação da conexão: {status}
"""
    console.print(Panel(result.strip(), title="Análise de Download", style="cyan"))
    post_test_menu(result.strip(), "teste_download")
def wifi_site_survey():
    console.rule("[bold blue]Site Survey Wi-Fi - Redes Visíveis[/bold blue]")

    if subprocess.run("which nmcli", shell=True, stdout=subprocess.DEVNULL).returncode != 0:
        result = "Erro: 'nmcli' não encontrado. Instale o NetworkManager para usar esta função."
        console.print(Panel(result, title="Erro Wi-Fi", style="red"))
        post_test_menu(result, "wifi_survey")
        return

    out, _ = run_command("nmcli -f SSID,BSSID,SIGNAL,SECURITY,CHAN device wifi list")
    lines = out.splitlines()
    if len(lines) < 2:
        result = "Nenhuma rede Wi-Fi encontrada."
        console.print(Panel(result, title="Site Survey", style="yellow"))
        post_test_menu(result, "wifi_survey")
        return

    table = Table(title="Redes Wi-Fi detectadas")
    table.add_column("SSID", style="cyan", no_wrap=True)
    table.add_column("BSSID", style="magenta")
    table.add_column("Sinal (%)", style="green")
    table.add_column("Segurança", style="red")
    table.add_column("Canal", style="yellow")

    output_str = ""  # para log
    for line in lines[1:]:
        parts = line.strip().split(None, 4)
        if len(parts) == 5:
            ssid, bssid, signal, security, chan = parts
        else:
            ssid, bssid, signal, security, chan = (parts + [""] * (5 - len(parts)))
        table.add_row(ssid, bssid, signal, security, chan)
        output_str += f"{ssid} | {bssid} | {signal} | {security} | {chan}\n"

    console.print(table)
    post_test_menu(output_str.strip(), "wifi_survey")

def netcat_test():
    console.rule("[bold blue]Teste de Conectividade com Netcat[/bold blue]")

    if subprocess.run("which nc", shell=True, stdout=subprocess.DEVNULL).returncode != 0:
        result = "Comando 'nc' (netcat) não encontrado. Instale com: sudo apt install netcat"
        console.print(Panel(result, title="Netcat - Erro", style="red"))
        post_test_menu(result, "netcat_teste")
        return

    host = Prompt.ask("Digite o IP ou domínio de destino (ex: 8.8.8.8)")
    port = Prompt.ask("Digite a porta a ser testada (ex: 53)")
    proto = Prompt.ask("Tipo de conexão", choices=["tcp", "udp"], default="tcp")

    cmd = f"nc -zv -w 3 {'-u' if proto == 'udp' else ''} {host} {port}"
    result, _ = run_command(cmd)

    painel = f"Host: {host}\nPorta: {port} ({proto.upper()})\n\nResultado:\n{result}"
    console.print(Panel(painel, title="Resultado - Netcat", style="cyan"))
    post_test_menu(painel, "netcat_teste")

def whois_lookup():
    console.rule("[bold blue]Consulta WHOIS - IP ou Domínio[/bold blue]")

    if subprocess.run("which whois", shell=True, stdout=subprocess.DEVNULL).returncode != 0:
        result = "Comando 'whois' não encontrado. Instale com: sudo apt install whois"
        console.print(Panel(result, title="Erro WHOIS", style="red"))
        post_test_menu(result, "whois")
        return

    alvo = Prompt.ask("Digite o IP ou domínio para consulta WHOIS (ex: 8.8.8.8 ou google.com)")
    result, _ = run_command(f"whois {alvo}")

    console.print(Panel(result, title=f"Resultado WHOIS para {alvo}", style="cyan"))
    post_test_menu(result, f"whois_{alvo.replace('.', '_')}")


# ========== MENUS ==========

def submenu_basico():
    opcoes = {
        "1": ("Interfaces Ativas", diagnostico_interfaces),
        "2": ("IP e Rota", diagnostico_ip_rota),
        "3": ("Ping Gateway", diagnostico_ping_gateway),
        "4": ("Ping Customizado", diagnostico_ping_custom),
        "5": ("Testes DNS", diagnostico_dns),
        "6": ("Teste de Portas", diagnostico_portas),
        "7": ("IP Público", diagnostico_ip_publico),
        "8": ("Logs DHCP", diagnostico_dhcp),
        "9": ("Latência e Jitter", diagnostico_latency_jitter),
        "0": ("Voltar", None)
    }
    menu_sub("Funções Básicas", opcoes)

def submenu_avancado():
    opcoes = {
        "1": ("SpeedTest CLI", diagnostico_speedtest),
        "2": ("Rota por Interface", diagnostico_rota_interface),
        "3": ("Captive Portal", diagnostico_captive),
        "4": ("Bloqueio DNS (porta 53)", diagnostico_dns_bloqueado),
        "5": ("MTU Máximo", diagnostico_mtu),
        "6": ("Múltiplos Gateways", diagnostico_multiplos_gateways),
        "7": ("Traceroute", diagnostico_traceroute),
        "8": ("MTR", diagnostico_mtr),
        "9": ("Netdiscover", netdiscover_custom),
        "10": ("Mudar IP local", set_static_ip),
        "11": ("Teste de Download", test_download_speed),
        "12": ("Site Survey", wifi_site_survey),
        "13": ("Netcat", netcat_test),
        "14": ("How Is?", whois_lookup),
        "0": ("Voltar", None)
    }
    menu_sub("Funções Avançadas", opcoes)

def menu_sub(titulo, opcoes):
    while True:
        console.rule(f"[bold green]{titulo}")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Opção", style="cyan")
        table.add_column("Descrição")
        for k, v in opcoes.items():
            table.add_row(k, v[0])
        console.print(table)
        escolha = input("Escolha: ").strip()
        if escolha == "0":
            break
        elif escolha in opcoes:
            func = opcoes[escolha][1]
            if func:
                func()
        else:
            console.print("[red]Opção inválida.[/red]")


def analise_prognostico():
    console.rule("[bold blue]Análise Inteligente de Diagnósticos[/bold blue]")
    if not os.path.exists(LOG_DIR):
        console.print("[red]Nenhum log encontrado para análise.[/red]")
        return

    arquivos = sorted([f for f in os.listdir(LOG_DIR) if f.endswith(".json")], reverse=True)
    if not arquivos:
        console.print("[red]Nenhum log JSON disponível.[/red]")
        return

    table = Table(title="Selecione um log para análise")
    table.add_column("Nº", style="cyan")
    table.add_column("Arquivo", style="green")
    for i, arq in enumerate(arquivos[:10]):
        table.add_row(str(i+1), arq)
    console.print(table)

    escolha = Prompt.ask("Número do arquivo", choices=[str(i+1) for i in range(len(arquivos[:10]))])
    escolhido = arquivos[int(escolha)-1]
    with open(os.path.join(LOG_DIR, escolhido), encoding="utf-8") as f:
        dados = json.load(f)

    output = dados.get("output", "")
    diagnostico = []

    perda_match = re.search(r"(\\d+)% packet loss", output)
    if perda_match and int(perda_match.group(1)) > 10:
        diagnostico.append("🔴 Alta perda de pacotes")

    latencia_match = re.search(r"Latência média: (\d+\.\d+)", output)
    if latencia_match and float(latencia_match.group(1)) > 150:
        diagnostico.append("🔴 Latência excessiva (>150ms)")

    vel_match = re.search(r"Velocidade média: (\d+\.\d+)", output)
    if vel_match and float(vel_match.group(1)) < 10:
        diagnostico.append("🟠 Velocidade baixa (<10Mbps)")

    if not diagnostico:
        resumo = "✅ Nenhum problema crítico identificado."
    else:
        resumo = "\n".join(diagnostico)

    console.print(Panel(resumo, title="Prognóstico da Rede", style="magenta"))
    post_test_menu(resumo, "prognostico")

def menu():
    while True:
        console.rule("[bold blue]Diagnóstico de Rede")
        table = Table(show_header=True, header_style="bold green")
        table.add_column("Opção", style="cyan")
        table.add_column("Categoria")
        table.add_row("1", "Funções Básicas")
        table.add_row("2", "Funções Avançadas")
        table.add_row("3", "Análise de Prognóstico")
        table.add_row("0", "Sair")
        console.print(table)
        escolha = input("Escolha: ").strip()
        if escolha == "1":
            submenu_basico()
        elif escolha == "2":
            submenu_avancado()
        elif escolha == "3":
            analise_prognostico()
        elif escolha == "0":
            console.print("[bold red]Saindo...[/bold red]")
            break
        else:
            console.print("[red]Opção inválida.[/red]")

if __name__ == "__main__":
    menu()
