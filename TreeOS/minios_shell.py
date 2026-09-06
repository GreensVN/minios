#!/usr/bin/env python3
"""
MiniOS Enhanced System Monitor and Shell v2.0
Công cụ giám sát và quản lý hệ thống nâng cao cho MiniOS
"""

import sys
import time
import random
import threading
from datetime import datetime
from collections import deque

# ========== ANSI Colors ==========
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'

# ========== System Monitor ==========
class SystemMonitor:
    """Giám sát các thông số hệ thống"""
    
    def __init__(self):
        self.start_time = time.time()
        self.cpu_history = deque(maxlen=60)
        self.memory_history = deque(maxlen=60)
        self.disk_history = deque(maxlen=60)
        self.network_rx = 0
        self.network_tx = 0
        self.process_count = 0
        self.running = False
        self.monitor_thread = None
        
    def start_monitoring(self):
        """Bật monitoring thread"""
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Tắt monitoring thread"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        while self.running:
            self.cpu_history.append(self.get_cpu_usage())
            self.memory_history.append(self.get_memory_info()['percent'])
            self.disk_history.append(self.get_disk_info()['percent'])
            time.sleep(1)
    
    def get_uptime(self):
        """Lấy thời gian hoạt động"""
        uptime = time.time() - self.start_time
        days = int(uptime // 86400)
        hours = int((uptime % 86400) // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        
        if days > 0:
            return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_cpu_usage(self):
        """Giả lập CPU usage"""
        return random.randint(10, 85)
    
    def get_memory_info(self):
        """Giả lập memory info"""
        total = 256 * 1024 * 1024  # 256 MB
        used = random.randint(50000000, 150000000)
        free = total - used
        percent = (used / total) * 100
        return {
            'total': total,
            'used': used,
            'free': free,
            'percent': percent
        }
    
    def get_disk_info(self):
        """Giả lập disk info"""
        total = 10 * 1024 * 1024 * 1024  # 10 GB
        used = random.randint(2000000000, 8000000000)
        free = total - used
        percent = (used / total) * 100
        return {
            'total': total,
            'used': used,
            'free': free,
            'percent': percent
        }
    
    def get_network_stats(self):
        """Giả lập network statistics"""
        self.network_rx += random.randint(100, 1000)
        self.network_tx += random.randint(50, 500)
        return {
            'rx': self.network_rx,
            'tx': self.network_tx
        }
    
    def get_cpu_temperature(self):
        """Giả lập CPU temperature"""
        return random.randint(35, 70)
    
    def draw_bar(self, percent, width=50, char='█'):
        """Vẽ thanh progress bar"""
        filled = int(width * percent / 100)
        empty = width - filled
        
        if percent < 50:
            color = Colors.GREEN
        elif percent < 75:
            color = Colors.YELLOW
        else:
            color = Colors.RED
        
        return f"{color}{char * filled}{Colors.RESET}{'░' * empty}"
    
    def display_dashboard(self):
        """Hiển thị dashboard giám sát"""
        print("\033[2J\033[H", end='')  # Clear screen
        
        # Header
        print(Colors.CYAN + Colors.BOLD)
        print("╔" + "═" * 78 + "╗")
        print("║" + " " * 25 + "MiniOS System Monitor v2.0" + " " * 27 + "║")
        print("╚" + "═" * 78 + "╝")
        print(Colors.RESET)
        
        # Time and Uptime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        uptime = self.get_uptime()
        print(f"\n{Colors.BOLD}Time:{Colors.RESET} {now}")
        print(f"{Colors.BOLD}Uptime:{Colors.RESET} {uptime}")
        
        # CPU
        cpu = self.get_cpu_usage()
        temp = self.get_cpu_temperature()
        print(f"\n{Colors.BOLD}CPU Usage:{Colors.RESET} {cpu}% (Temp: {temp}°C)")
        print(self.draw_bar(cpu))
        
        # CPU History
        if len(self.cpu_history) > 0:
            print(f"{Colors.BOLD}CPU History (60s):{Colors.RESET}")
            self._draw_sparkline(list(self.cpu_history))
        
        # Memory
        mem = self.get_memory_info()
        print(f"\n{Colors.BOLD}Memory:{Colors.RESET} {mem['used']//1024//1024} MB / {mem['total']//1024//1024} MB ({mem['percent']:.1f}%)")
        print(self.draw_bar(mem['percent']))
        
        # Disk
        disk = self.get_disk_info()
        print(f"\n{Colors.BOLD}Disk:{Colors.RESET} {disk['used']//1024//1024//1024} GB / {disk['total']//1024//1024//1024} GB ({disk['percent']:.1f}%)")
        print(self.draw_bar(disk['percent']))
        
        # Network
        net = self.get_network_stats()
        print(f"\n{Colors.BOLD}Network:{Colors.RESET}")
        print(f"  RX: {net['rx']//1024} KB")
        print(f"  TX: {net['tx']//1024} KB")
        
        # Footer
        print(f"\n{Colors.YELLOW}Press Ctrl+C to return to shell{Colors.RESET}")
        print("─" * 80)
    
    def _draw_sparkline(self, data):
        """Vẽ sparkline chart"""
        if not data:
            return
        
        chars = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']
        max_val = max(data) if max(data) > 0 else 1
        
        line = ""
        for val in data:
            idx = int((val / max_val) * (len(chars) - 1))
            line += chars[idx]
        
        print(line)

# ========== Process Manager ==========
class ProcessManager:
    """Quản lý processes"""
    
    def __init__(self):
        self.processes = {}
        self.next_pid = 1
        
    def create_process(self, name, priority=5, user="root"):
        """Tạo process mới"""
        pid = self.next_pid
        self.processes[pid] = {
            'pid': pid,
            'name': name,
            'priority': priority,
            'state': 'running',
            'start_time': time.time(),
            'cpu_time': random.uniform(0, 100),
            'memory': random.randint(1024, 10240),
            'user': user,
            'threads': 1
        }
        self.next_pid += 1
        return pid
    
    def kill_process(self, pid):
        """Kill process"""
        if pid in self.processes:
            self.processes[pid]['state'] = 'terminated'
            del self.processes[pid]
            return True
        return False
    
    def suspend_process(self, pid):
        """Suspend process"""
        if pid in self.processes:
            self.processes[pid]['state'] = 'suspended'
            return True
        return False
    
    def resume_process(self, pid):
        """Resume process"""
        if pid in self.processes:
            self.processes[pid]['state'] = 'running'
            return True
        return False
    
    def list_processes(self, sort_by='pid'):
        """Liệt kê processes"""
        procs = sorted(self.processes.values(), key=lambda x: x[sort_by])
        
        print(f"\n{Colors.BOLD}PID   NAME                 USER     STATE      PRI  MEMORY   CPU_TIME  THREADS{Colors.RESET}")
        print("─" * 85)
        
        for proc in procs:
            state_color = Colors.GREEN if proc['state'] == 'running' else Colors.YELLOW
            print(f"{proc['pid']:<5} {proc['name']:<20} {proc['user']:<8} "
                  f"{state_color}{proc['state']:<10}{Colors.RESET} "
                  f"{proc['priority']:<4} {proc['memory']:<8} "
                  f"{proc['cpu_time']:<9.2f} {proc['threads']}")
    
    def get_process_count(self):
        """Lấy số lượng processes"""
        return len(self.processes)
    
    def get_process_info(self, pid):
        """Lấy thông tin process"""
        return self.processes.get(pid)

# ========== Filesystem Manager ==========
class FilesystemManager:
    """Quản lý filesystem ảo"""
    
    def __init__(self):
        self.root = {
            'type': 'dir',
            'children': {
                'bin': {'type': 'dir', 'children': {}},
                'etc': {'type': 'dir', 'children': {
                    'config.sys': {'type': 'file', 'size': 256, 'content': 'KERNEL_MODE=protected\n'}
                }},
                'home': {'type': 'dir', 'children': {}},
                'usr': {'type': 'dir', 'children': {}},
                'var': {'type': 'dir', 'children': {}},
                'tmp': {'type': 'dir', 'children': {}},
                'dev': {'type': 'dir', 'children': {}},
            }
        }
        self.current_path = '/'
    
    def get_node(self, path):
        """Lấy node tại path"""
        if path == '/':
            return self.root
        
        parts = path.strip('/').split('/')
        node = self.root
        
        for part in parts:
            if 'children' in node and part in node['children']:
                node = node['children'][part]
            else:
                return None
        
        return node
    
    def resolve(self, path):
        """Chuẩn hoá path (tương đối / tuyệt đối, '.' và '..')"""
        if not path:
            return self.current_path
        base = [] if path.startswith('/') else [p for p in self.current_path.split('/') if p]
        for part in path.split('/'):
            if part in ('', '.'):
                continue
            if part == '..':
                if base:
                    base.pop()
            else:
                base.append(part)
        return '/' + '/'.join(base)
    
    def cd(self, path):
        """Đổi thư mục hiện tại"""
        target = self.resolve(path)
        node = self.get_node(target)
        if node and node['type'] == 'dir':
            self.current_path = target
            return True
        return False
    
    def tree(self, path=None, prefix=''):
        """Trả về các dòng cây thư mục"""
        node = self.get_node(self.resolve(path))
        if not node or node['type'] != 'dir':
            return []
        lines = []
        items = sorted(node['children'].items())
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if child['type'] == 'dir' else ''}")
            if child['type'] == 'dir':
                lines.extend(self._tree_node(child, prefix + ('    ' if last else '│   ')))
        return lines
    
    def _tree_node(self, node, prefix):
        lines = []
        items = sorted(node['children'].items())
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if child['type'] == 'dir' else ''}")
            if child['type'] == 'dir':
                lines.extend(self._tree_node(child, prefix + ('    ' if last else '│   ')))
        return lines
    
    def ls(self, path=None):
        """List directory"""
        path = self.resolve(path)
        
        node = self.get_node(path)
        if not node or node['type'] != 'dir':
            return []
        
        entries = []
        for name, child in node['children'].items():
            icon = '📁' if child['type'] == 'dir' else '📄'
            size = child.get('size', 0) if child['type'] == 'file' else '-'
            entries.append((icon, name, size))
        
        return entries
    
    def mkdir(self, name, path=None):
        """Create directory"""
        node = self.get_node(self.resolve(path))
        if node and node['type'] == 'dir' and name and '/' not in name and name not in node['children']:
            node['children'][name] = {'type': 'dir', 'children': {}}
            return True
        return False
    
    def touch(self, name, path=None):
        """Create file"""
        node = self.get_node(self.resolve(path))
        if node and node['type'] == 'dir' and name and '/' not in name:
            if name not in node['children']:
                node['children'][name] = {'type': 'file', 'size': 0, 'content': ''}
            return True
        return False

# ========== MiniOS Shell ==========
class MiniOSShell:
    """Enhanced shell với nhiều tính năng"""
    
    def __init__(self):
        self.monitor = SystemMonitor()
        self.process_manager = ProcessManager()
        self.fs_manager = FilesystemManager()
        self.running = True
        self.command_history = []
        self.aliases = {
            'll': 'ls -l',
            'la': 'ls -a',
            'cls': 'clear'
        }
        
        # Khởi tạo processes mẫu
        self.process_manager.create_process("kernel_idle", 0, "root")
        self.process_manager.create_process("system_monitor", 10, "root")
        self.process_manager.create_process("shell", 5, "user")
        self.process_manager.create_process("network_daemon", 7, "root")
        
        self.monitor.start_monitoring()
    
    def print_banner(self):
        """In banner khởi động"""
        banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║     ███╗   ███╗██╗███╗   ██╗██╗     ██████╗ ███████╗                     ║
║     ████╗ ████║██║████╗  ██║██║    ██╔═══██╗██╔════╝                     ║
║     ██╔████╔██║██║██╔██╗ ██║██║    ██║   ██║███████╗                     ║
║     ██║╚██╔╝██║██║██║╚██╗██║██║    ██║   ██║╚════██║                     ║
║     ██║ ╚═╝ ██║██║██║ ╚████║██║    ╚██████╔╝███████║                     ║
║     ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═════╝ ╚══════╝                     ║
║                                                                            ║
║                  Enhanced Shell v2.0 - All Systems Online                 ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
{Colors.RESET}

{Colors.GREEN}Welcome to MiniOS Enhanced Shell!{Colors.RESET}
Type {Colors.YELLOW}'help'{Colors.RESET} for available commands or {Colors.YELLOW}'tutorial'{Colors.RESET} for a quick guide.
"""
        print(banner)
    
    def cmd_help(self, args):
        """Hiển thị help"""
        commands = {
            'System Information': [
                ('help', 'Show this help message'),
                ('about', 'About MiniOS'),
                ('info', 'Show system information'),
                ('uptime', 'Show system uptime'),
                ('date', 'Show current date and time'),
                ('uname', 'Print system information'),
            ],
            'Process Management': [
                ('ps', 'List all processes'),
                ('top', 'Display processes (sorted by CPU)'),
                ('kill <pid>', 'Kill a process'),
                ('suspend <pid>', 'Suspend a process'),
                ('resume <pid>', 'Resume a process'),
                ('start <name> [pri]', 'Start a new process'),
            ],
            'System Monitor': [
                ('monitor', 'Start system monitor dashboard'),
                ('meminfo', 'Show memory information'),
                ('diskinfo', 'Show disk information'),
                ('netstat', 'Show network statistics'),
                ('cpu', 'Show CPU information'),
            ],
            'Filesystem': [
                ('ls [path]', 'List directory contents'),
                ('pwd', 'Print working directory'),
                ('cd <dir>', 'Change directory'),
                ('mkdir <name>', 'Create directory'),
                ('touch <name>', 'Create file'),
                ('tree', 'Show directory tree'),
            ],
            'Utilities': [
                ('clear', 'Clear screen'),
                ('history', 'Show command history'),
                ('alias', 'Show/set aliases'),
                ('echo <text>', 'Print text'),
                ('sleep <sec>', 'Sleep for seconds'),
            ],
            'System Control': [
                ('reboot', 'Reboot system'),
                ('shutdown', 'Shutdown system'),
                ('exit', 'Exit shell'),
            ]
        }
        
        print()
        for category, cmds in commands.items():
            print(f"{Colors.CYAN}{Colors.BOLD}{category}:{Colors.RESET}")
            for cmd, desc in cmds:
                print(f"  {Colors.GREEN}{cmd:<20}{Colors.RESET} - {desc}")
            print()
    
    def cmd_monitor(self, args):
        """Bật system monitor"""
        print(f"{Colors.YELLOW}Starting system monitor... (Press Ctrl+C to stop){Colors.RESET}")
        try:
            while True:
                self.monitor.display_dashboard()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n\n{Colors.GREEN}Monitor stopped.{Colors.RESET}\n")
    
    def cmd_ps(self, args):
        """List processes"""
        sort_by = args[0] if args else 'pid'
        if sort_by not in ['pid', 'cpu_time', 'memory', 'name']:
            sort_by = 'pid'
        self.process_manager.list_processes(sort_by)
        print()
    
    def cmd_top(self, args):
        """Show top processes"""
        self.process_manager.list_processes('cpu_time')
        print()
    
    def cmd_info(self, args):
        """Hiển thị system info"""
        mem = self.monitor.get_memory_info()
        disk = self.monitor.get_disk_info()
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}╔═══════════════════════════════════════════════════════════╗")
        print("║           MiniOS System Information v2.0                  ║")
        print(f"╚═══════════════════════════════════════════════════════════╝{Colors.RESET}")
        print(f"\n{Colors.BOLD}OS:{Colors.RESET}           MiniOS v2.0 Enhanced")
        print(f"{Colors.BOLD}Architecture:{Colors.RESET} x86 (32-bit)")
        print(f"{Colors.BOLD}Kernel:{Colors.RESET}       1.0.0-enhanced")
        print(f"{Colors.BOLD}Build Date:{Colors.RESET}   {datetime.now().strftime('%Y-%m-%d')}")
        print(f"{Colors.BOLD}Uptime:{Colors.RESET}       {self.monitor.get_uptime()}")
        print(f"{Colors.BOLD}Processes:{Colors.RESET}    {self.process_manager.get_process_count()}")
        print(f"{Colors.BOLD}Memory:{Colors.RESET}       {mem['used']//1024//1024} MB / {mem['total']//1024//1024} MB")
        print(f"{Colors.BOLD}Disk:{Colors.RESET}         {disk['used']//1024//1024//1024} GB / {disk['total']//1024//1024//1024} GB")
        print()
    
    def cmd_ls(self, args):
        """List directory"""
        paths = [a for a in args if not a.startswith('-')]
        path = paths[0] if paths else None
        if self.fs_manager.get_node(self.fs_manager.resolve(path)) is None:
            print(f"{Colors.RED}ls: no such directory: {path}{Colors.RESET}")
            return
        entries = self.fs_manager.ls(path)
        if not entries:
            print("(empty)")
            return
        
        print()
        for icon, name, size in entries:
            size_str = f"{size:>8}" if isinstance(size, int) else f"{size:>8}"
            print(f"{icon}  {name:<30} {size_str}")
        print()
    
    def cmd_about(self, args):
        """About"""
        print(f"\n{Colors.CYAN}{Colors.BOLD}MiniOS Shell v2.0{Colors.RESET} - host-side simulator of the MiniOS command shell.")
        print("The real kernel lives in Kernel.c; build it with 'make' and run 'make run'.\n")
    
    def cmd_date(self, args):
        """Ngày giờ hiện tại"""
        print(datetime.now().strftime('%a %b %d %H:%M:%S %Y'))
    
    def cmd_uname(self, args):
        """uname"""
        print("MiniOS 4.1.0 i686 MiniOS-Shell" if args and args[0] == '-a' else "MiniOS")
    
    def cmd_kill(self, args):
        """Kill process"""
        if not args or not args[0].isdigit():
            print(f"{Colors.RED}Usage: kill <pid>{Colors.RESET}")
            return
        pid = int(args[0])
        if pid == 1:
            print(f"{Colors.RED}Cannot kill kernel_idle (pid 1){Colors.RESET}")
        elif self.process_manager.kill_process(pid):
            print(f"Process {pid} terminated")
        else:
            print(f"{Colors.RED}No such process: {pid}{Colors.RESET}")
    
    def cmd_suspend(self, args):
        """Suspend process"""
        if not args or not args[0].isdigit() or not self.process_manager.suspend_process(int(args[0])):
            print(f"{Colors.RED}Usage: suspend <pid>{Colors.RESET}")
        else:
            print(f"Process {args[0]} suspended")
    
    def cmd_resume(self, args):
        """Resume process"""
        if not args or not args[0].isdigit() or not self.process_manager.resume_process(int(args[0])):
            print(f"{Colors.RED}Usage: resume <pid>{Colors.RESET}")
        else:
            print(f"Process {args[0]} resumed")
    
    def cmd_start(self, args):
        """Start process"""
        if not args:
            print(f"{Colors.RED}Usage: start <name> [priority]{Colors.RESET}")
            return
        pri = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
        pid = self.process_manager.create_process(args[0], pri, "user")
        print(f"Started '{args[0]}' with pid {pid}")
    
    def cmd_meminfo(self, args):
        """Memory info"""
        mem = self.monitor.get_memory_info()
        print(f"\nMemTotal: {mem['total']//1024:>10} kB\nMemUsed:  {mem['used']//1024:>10} kB\n"
              f"MemFree:  {mem['free']//1024:>10} kB\nUsage:    {mem['percent']:>9.1f} %\n")
    
    def cmd_diskinfo(self, args):
        """Disk info"""
        disk = self.monitor.get_disk_info()
        gb = 1024 ** 3
        print(f"\nFilesystem   Size   Used  Avail  Use%\n/dev/hda  {disk['total']/gb:5.1f}G {disk['used']/gb:5.1f}G "
              f"{disk['free']/gb:5.1f}G {disk['percent']:4.0f}%\n")
    
    def cmd_netstat(self, args):
        """Network stats"""
        net = self.monitor.get_network_stats()
        print(f"\neth0  RX bytes: {net['rx']:>12}  TX bytes: {net['tx']:>12}\n")
    
    def cmd_cpu(self, args):
        """CPU info"""
        print(f"\nCPU usage: {self.monitor.get_cpu_usage()}%   temperature: {self.monitor.get_cpu_temperature()}°C\n")
    
    def cmd_pwd(self, args):
        """Print working directory"""
        print(self.fs_manager.current_path)
    
    def cmd_cd(self, args):
        """Change directory"""
        target = args[0] if args else '/'
        if not self.fs_manager.cd(target):
            print(f"{Colors.RED}cd: no such directory: {target}{Colors.RESET}")
    
    def cmd_mkdir(self, args):
        """Create directory"""
        if not args or not self.fs_manager.mkdir(args[0]):
            print(f"{Colors.RED}mkdir: cannot create directory{Colors.RESET}")
    
    def cmd_touch(self, args):
        """Create file"""
        if not args or not self.fs_manager.touch(args[0]):
            print(f"{Colors.RED}touch: cannot create file{Colors.RESET}")
    
    def cmd_tree(self, args):
        """Directory tree"""
        path = args[0] if args else None
        print(self.fs_manager.resolve(path))
        for line in self.fs_manager.tree(path):
            print(line)
        print()
    
    def cmd_alias(self, args):
        """Show/set aliases"""
        if args and '=' in ' '.join(args):
            name, _, value = ' '.join(args).partition('=')
            self.aliases[name.strip()] = value.strip().strip('"\'')
        else:
            for name, value in self.aliases.items():
                print(f"alias {name}='{value}'")
    
    def cmd_echo(self, args):
        """Print text"""
        print(' '.join(args))
    
    def cmd_sleep(self, args):
        """Sleep"""
        try:
            time.sleep(float(args[0]) if args else 1)
        except (ValueError, KeyboardInterrupt):
            pass
    
    def cmd_reboot(self, args):
        """Reboot (simulated)"""
        print(f"{Colors.YELLOW}Rebooting...{Colors.RESET}")
        self.command_history.clear()
        self.fs_manager.current_path = '/'
        self.print_banner()
    
    def cmd_shutdown(self, args):
        """Shutdown"""
        self.cmd_exit(args)
    
    def cmd_clear(self, args):
        """Clear màn hình"""
        print("\033[2J\033[H", end='')
    
    def cmd_uptime(self, args):
        """Show uptime"""
        print(f"System uptime: {self.monitor.get_uptime()}")
    
    def cmd_history(self, args):
        """Show command history"""
        print()
        for i, cmd in enumerate(self.command_history[-20:], 1):
            print(f"{i:3d}  {cmd}")
        print()
    
    def cmd_exit(self, args):
        """Exit shell"""
        print(f"\n{Colors.CYAN}Shutting down shell...{Colors.RESET}")
        self.monitor.stop_monitoring()
        print(f"{Colors.GREEN}Goodbye!{Colors.RESET}\n")
        self.running = False
    
    def execute_command(self, command_line):
        """Execute command"""
        if not command_line.strip():
            return
        
        # Save to history
        self.command_history.append(command_line)
        
        parts = command_line.strip().split()
        # Expand aliases (whole first word only)
        if parts[0] in self.aliases:
            parts = self.aliases[parts[0]].split() + parts[1:]
        cmd = parts[0].lower()
        args = parts[1:]
        
        # Command dispatch
        method_name = f"cmd_{cmd}"
        if hasattr(self, method_name):
            try:
                method = getattr(self, method_name)
                method(args)
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        else:
            print(f"{Colors.RED}Unknown command: {cmd}{Colors.RESET}")
            print(f"Type {Colors.YELLOW}'help'{Colors.RESET} for available commands.")
    
    def run(self):
        """Main shell loop"""
        self.print_banner()
        
        while self.running:
            try:
                prompt = f"{Colors.GREEN}{Colors.BOLD}MiniOS{Colors.RESET}:{Colors.BLUE}{self.fs_manager.current_path}{Colors.RESET}$ "
                command = input(prompt)
                self.execute_command(command)
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}Use 'exit' to quit.{Colors.RESET}")
            except EOFError:
                break
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")

# ========== Main Entry Point ==========
def main():
    """Entry point"""
    try:
        shell = MiniOSShell()
        shell.run()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())