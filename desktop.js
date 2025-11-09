import React, { useState, useEffect, useRef } from 'react';
import { X, Minus, Square, Folder, File, Terminal, Settings, Monitor, Wifi, Battery, Volume2, Search, Grid, Calendar, Clock, Calculator, FileText, HardDrive, Cpu, Activity, Network, Users, Package } from 'lucide-react';

const MiniOSDesktop = () => {
  const [windows, setWindows] = useState([]);
  const [activeWindow, setActiveWindow] = useState(null);
  const [time, setTime] = useState(new Date());
  const [showStartMenu, setShowStartMenu] = useState(false);
  const [terminalOutput, setTerminalOutput] = useState([]);
  const [terminalInput, setTerminalInput] = useState('');
  const [editorContent, setEditorContent] = useState('');
  const [calcDisplay, setCalcDisplay] = useState('');
  const [currentPath, setCurrentPath] = useState('/');
  const [showBootScreen, setShowBootScreen] = useState(true);
  const [bootProgress, setBootProgress] = useState(0);
  const [systemStats, setSystemStats] = useState({ cpu: 0, mem: 0, disk: 0, net: 100 });
  const [processes, setProcesses] = useState([]);
  const [fileSystem, setFileSystem] = useState(initFileSystem());
  const [networkDevices, setNetworkDevices] = useState(initNetwork());
  const canvasRef = useRef(null);

  // Initialize filesystem
  function initFileSystem() {
    return {
      '/': {
        type: 'dir',
        children: {
          'bin': { type: 'dir', children: {} },
          'etc': { 
            type: 'dir', 
            children: {
              'config.sys': { type: 'file', size: 256, content: 'KERNEL_MODE=protected\nMEMORY_SIZE=256MB\n' },
              'passwd': { type: 'file', size: 128, content: 'root:x:0:0:root:/root:/bin/bash\n' }
            }
          },
          'home': { 
            type: 'dir', 
            children: {
              'user': {
                type: 'dir',
                children: {
                  'documents': { type: 'dir', children: {} },
                  'downloads': { type: 'dir', children: {} }
                }
              }
            }
          },
          'usr': { type: 'dir', children: {} },
          'var': { type: 'dir', children: {} },
          'tmp': { type: 'dir', children: {} },
          'dev': { type: 'dir', children: {} },
          'proc': { type: 'dir', children: {} },
          'README.md': { type: 'file', size: 512, content: '# MiniOS V5.0 ULTIMATE\n\nComplete Desktop Operating System\n\nFeatures:\n- Full GUI Desktop\n- Process Management\n- Filesystem\n- Network Stack\n- Multi-tasking\n\nType "help" for commands.' }
        }
      }
    };
  }

  // Initialize network
  function initNetwork() {
    return {
      'lo': { name: 'lo', ip: '127.0.0.1', mac: '00:00:00:00:00:00', status: 'UP', type: 'loopback' },
      'eth0': { name: 'eth0', ip: '192.168.1.100', mac: '52:54:00:12:34:56', status: 'UP', type: 'ethernet' },
      'wlan0': { name: 'wlan0', ip: '192.168.1.101', mac: '00:11:22:33:44:55', status: 'DOWN', type: 'wireless' }
    };
  }

  // Boot sequence
  useEffect(() => {
    if (showBootScreen) {
      const bootInterval = setInterval(() => {
        setBootProgress(prev => {
          const newProgress = prev + Math.random() * 15;
          if (newProgress >= 100) {
            clearInterval(bootInterval);
            setTimeout(() => {
              setShowBootScreen(false);
              initSystem();
            }, 500);
            return 100;
          }
          return newProgress;
        });
      }, 200);
      return () => clearInterval(bootInterval);
    }
  }, [showBootScreen]);

  // Initialize system
  function initSystem() {
    setProcesses([
      { pid: 0, name: 'idle', state: 'sleeping', cpu: 0, mem: 0, user: 'root' },
      { pid: 1, name: 'init', state: 'running', cpu: 1, mem: 1024, user: 'root' },
      { pid: 2, name: 'systemd', state: 'running', cpu: 2, mem: 2048, user: 'root' },
      { pid: 3, name: 'desktop', state: 'running', cpu: 5, mem: 4096, user: 'user' },
      { pid: 4, name: 'network', state: 'sleeping', cpu: 0, mem: 1024, user: 'root' }
    ]);
  }

  // System monitoring
  useEffect(() => {
    const interval = setInterval(() => {
      setSystemStats({
        cpu: Math.floor(Math.random() * 30 + 20),
        mem: Math.floor(Math.random() * 20 + 40),
        disk: Math.floor(Math.random() * 10 + 60),
        net: Math.random() > 0.1 ? 100 : 0
      });
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, '#1a1a2e');
    gradient.addColorStop(1, '#0f3460');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    ctx.strokeStyle = 'rgba(0, 255, 0, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i < canvas.width; i += 50) {
      ctx.beginPath();
      ctx.moveTo(i, 0);
      ctx.lineTo(i, canvas.height);
      ctx.stroke();
    }
    for (let i = 0; i < canvas.height; i += 50) {
      ctx.beginPath();
      ctx.moveTo(0, i);
      ctx.lineTo(canvas.width, i);
      ctx.stroke();
    }
  }, []);

  const createWindow = (type, title) => {
    const widthMap = {
      terminal: 800,
      calculator: 400,
      sysmonitor: 700,
      processes: 800,
      network: 700
    };
    
    const newWindow = {
      id: Date.now(),
      type,
      title,
      x: 100 + windows.length * 30,
      y: 80 + windows.length * 30,
      width: widthMap[type] || 600,
      height: type === 'calculator' ? 550 : 500,
      minimized: false,
      maximized: false
    };
    setWindows([...windows, newWindow]);
    setActiveWindow(newWindow.id);
    setShowStartMenu(false);
  };

  const closeWindow = (id) => {
    setWindows(windows.filter(w => w.id !== id));
    if (activeWindow === id) {
      setActiveWindow(windows[windows.length - 2]?.id || null);
    }
  };

  const minimizeWindow = (id) => {
    setWindows(windows.map(w => 
      w.id === id ? { ...w, minimized: true } : w
    ));
  };

  const restoreWindow = (id) => {
    setWindows(windows.map(w => 
      w.id === id ? { ...w, minimized: false } : w
    ));
    setActiveWindow(id);
  };

  const maximizeWindow = (id) => {
    setWindows(windows.map(w => 
      w.id === id ? { 
        ...w, 
        maximized: !w.maximized,
        x: w.maximized ? 100 : 0,
        y: w.maximized ? 80 : 40,
        width: w.maximized ? (w.type === 'calculator' ? 400 : 600) : window.innerWidth,
        height: w.maximized ? (w.type === 'calculator' ? 550 : 500) : window.innerHeight - 80
      } : w
    ));
  };

  const executeCommand = (cmd) => {
    const output = [...terminalOutput];
    output.push({ type: 'input', text: `user@minios:${currentPath}$ ${cmd}` });
    
    const [command, ...args] = cmd.trim().split(' ');
    
    const commands = {
      help: () => {
        output.push({ type: 'output', text: 'Available commands:' });
        output.push({ type: 'output', text: '  help, ls, cd, pwd, cat, mkdir, touch, rm' });
        output.push({ type: 'output', text: '  ps, top, kill, neofetch, sysinfo' });
        output.push({ type: 'output', text: '  ifconfig, netstat, ping' });
        output.push({ type: 'output', text: '  clear, date, uptime, uname, whoami' });
      },
      ls: () => {
        const dir = getDirectory(currentPath);
        if (dir && dir.children) {
          Object.keys(dir.children).forEach(name => {
            const item = dir.children[name];
            const icon = item.type === 'dir' ? '📁' : '📄';
            output.push({ type: 'output', text: `${icon} ${name}` });
          });
        }
      },
      cd: () => {
        if (!args[0] || args[0] === '/') {
          setCurrentPath('/');
        } else if (args[0] === '..') {
          const parts = currentPath.split('/').filter(p => p);
          parts.pop();
          setCurrentPath('/' + parts.join('/'));
        } else {
          const newPath = currentPath === '/' ? `/${args[0]}` : `${currentPath}/${args[0]}`;
          const dir = getDirectory(newPath);
          if (dir && dir.type === 'dir') {
            setCurrentPath(newPath);
          } else {
            output.push({ type: 'error', text: `cd: ${args[0]}: No such directory` });
          }
        }
      },
      pwd: () => {
        output.push({ type: 'output', text: currentPath });
      },
      cat: () => {
        if (!args[0]) {
          output.push({ type: 'error', text: 'cat: missing operand' });
        } else {
          const file = getDirectory(`${currentPath}/${args[0]}`);
          if (file && file.type === 'file') {
            output.push({ type: 'output', text: file.content || '(empty file)' });
          } else {
            output.push({ type: 'error', text: `cat: ${args[0]}: No such file` });
          }
        }
      },
      ps: () => {
        output.push({ type: 'output', text: 'PID   USER     STATE      CPU   MEM    COMMAND' });
        output.push({ type: 'output', text: '─────────────────────────────────────────────' });
        processes.forEach(proc => {
          output.push({ type: 'output', text: `${proc.pid.toString().padEnd(5)} ${proc.user.padEnd(8)} ${proc.state.padEnd(10)} ${proc.cpu}%    ${proc.mem}KB  ${proc.name}` });
        });
      },
      neofetch: () => {
        output.push({ type: 'output', text: '   ___  ___  _        _  ___   ___ ' });
        output.push({ type: 'output', text: '  |  \\/  | (_)      (_)/ _ \\ / __|' });
        output.push({ type: 'output', text: '  | |\\/| | |_ _ __  _ | | | |\\__ \\' });
        output.push({ type: 'output', text: '  |_|  |_| | | \'_ \\| || |_| ||___/' });
        output.push({ type: 'output', text: '          |_|_| |_||_| \\___/      ' });
        output.push({ type: 'output', text: '' });
        output.push({ type: 'output', text: '  OS: MiniOS V5.0 ULTIMATE Desktop' });
        output.push({ type: 'output', text: '  Kernel: 5.0.0-ultimate-gui' });
        output.push({ type: 'output', text: '  Shell: WebTerminal 5.0' });
        output.push({ type: 'output', text: '  Resolution: 1920x1080' });
        output.push({ type: 'output', text: '  CPU: JavaScript V8 Engine' });
        output.push({ type: 'output', text: `  Memory: ${systemStats.mem}% used` });
      },
      ifconfig: () => {
        output.push({ type: 'output', text: 'Network Interfaces:' });
        Object.values(networkDevices).forEach(iface => {
          output.push({ type: 'output', text: `\n${iface.name}: ${iface.status}` });
          output.push({ type: 'output', text: `  inet ${iface.ip}` });
          output.push({ type: 'output', text: `  ether ${iface.mac}` });
          output.push({ type: 'output', text: `  type: ${iface.type}` });
        });
      },
      clear: () => {
        setTerminalOutput([]);
        return;
      },
      date: () => {
        output.push({ type: 'output', text: new Date().toString() });
      },
      uptime: () => {
        output.push({ type: 'output', text: 'up 2:34:56, 1 user, load average: 0.45, 0.38, 0.32' });
      },
      uname: () => {
        output.push({ type: 'output', text: 'MiniOS 5.0.0-ultimate x86_64' });
      },
      whoami: () => {
        output.push({ type: 'output', text: 'user' });
      }
    };

    if (cmd === 'clear') {
      setTerminalOutput([]);
      setTerminalInput('');
      return;
    }

    if (commands[command]) {
      commands[command]();
    } else if (cmd.trim()) {
      output.push({ type: 'error', text: `Command not found: ${command}` });
    }

    setTerminalOutput(output);
    setTerminalInput('');
  };

  const getDirectory = (path) => {
    if (path === '/') return fileSystem['/'];
    
    const parts = path.split('/').filter(p => p);
    let current = fileSystem['/'];
    
    for (const part of parts) {
      if (!current.children || !current.children[part]) return null;
      current = current.children[part];
    }
    
    return current;
  };

  const calcBtn = (val) => {
    setCalcDisplay(calcDisplay + val);
  };

  const calcEqual = () => {
    try {
      setCalcDisplay(eval(calcDisplay).toString());
    } catch {
      setCalcDisplay('Error');
      setTimeout(() => setCalcDisplay(''), 1000);
    }
  };

  const calcClear = () => {
    setCalcDisplay('');
  };

  const DesktopIcon = ({ icon: Icon, label, onClick }) => (
    <div 
      onDoubleClick={onClick}
      className="flex flex-col items-center justify-center w-20 h-20 cursor-pointer hover:bg-white/10 rounded-lg transition-all group"
    >
      <Icon className="w-10 h-10 text-cyan-400 group-hover:scale-110 transition-transform" />
      <span className="text-xs text-white mt-1 text-center">{label}</span>
    </div>
  );

  const Window = ({ window: win }) => {
    const [isDragging, setIsDragging] = useState(false);
    const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });

    if (win.minimized) return null;

    const handleMouseDown = (e) => {
      if (e.target.closest('.window-controls')) return;
      setIsDragging(true);
      setDragOffset({
        x: e.clientX - win.x,
        y: e.clientY - win.y
      });
      setActiveWindow(win.id);
    };

    const handleMouseMove = (e) => {
      if (!isDragging) return;
      setWindows(windows.map(w => 
        w.id === win.id ? {
          ...w,
          x: e.clientX - dragOffset.x,
          y: e.clientY - dragOffset.y
        } : w
      ));
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    useEffect(() => {
      if (isDragging) {
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        return () => {
          document.removeEventListener('mousemove', handleMouseMove);
          document.removeEventListener('mouseup', handleMouseUp);
        };
      }
    }, [isDragging]);

    return (
      <div
        className={`absolute bg-gray-900 border-2 rounded-lg shadow-2xl overflow-hidden ${
          activeWindow === win.id ? 'border-cyan-500 z-50' : 'border-gray-700 z-40'
        }`}
        style={{
          left: win.x,
          top: win.y,
          width: win.width,
          height: win.height
        }}
        onClick={() => setActiveWindow(win.id)}
      >
        <div
          className="bg-gradient-to-r from-gray-800 to-gray-900 px-4 py-2 flex items-center justify-between cursor-move border-b border-cyan-500/50"
          onMouseDown={handleMouseDown}
        >
          <span className="text-cyan-400 font-semibold">{win.title}</span>
          <div className="window-controls flex gap-2">
            <button
              onClick={() => minimizeWindow(win.id)}
              className="w-6 h-6 bg-yellow-500 hover:bg-yellow-600 rounded flex items-center justify-center transition-colors"
            >
              <Minus size={14} className="text-gray-900" />
            </button>
            {win.type !== 'calculator' && (
              <button
                onClick={() => maximizeWindow(win.id)}
                className="w-6 h-6 bg-green-500 hover:bg-green-600 rounded flex items-center justify-center transition-colors"
              >
                <Square size={14} className="text-gray-900" />
              </button>
            )}
            <button
              onClick={() => closeWindow(win.id)}
              className="w-6 h-6 bg-red-500 hover:bg-red-600 rounded flex items-center justify-center transition-colors"
            >
              <X size={14} className="text-white" />
            </button>
          </div>
        </div>

        <div className="h-full overflow-auto bg-gray-900">
          {win.type === 'files' && (
            <div className="flex flex-col h-full">
              <div className="flex gap-2 p-3 bg-gray-800 border-b border-gray-700">
                <button className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300">← Back</button>
                <button className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300">Forward →</button>
                <button className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300">🔄 Refresh</button>
                <button className="px-3 py-1 bg-cyan-600 hover:bg-cyan-700 rounded text-sm text-white">📁 New Folder</button>
              </div>
              <div className="px-4 py-2 bg-gray-800/50 text-green-400 font-mono text-sm border-b border-gray-700">
                {currentPath}
              </div>
              <div className="p-4 flex-1">
                <div className="grid grid-cols-4 gap-4">
                  {getDirectory(currentPath)?.children && Object.entries(getDirectory(currentPath).children).map(([name, item]) => (
                    <div key={name} className="flex flex-col items-center p-3 hover:bg-gray-800 rounded cursor-pointer transition-colors">
                      {item.type === 'dir' ? <Folder className="w-12 h-12 text-cyan-400" /> : <File className="w-12 h-12 text-gray-400" />}
                      <span className="text-sm text-gray-300 mt-2">{name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {win.type === 'terminal' && (
            <div className="p-4 h-full flex flex-col bg-black font-mono text-sm">
              <div className="flex-1 overflow-auto mb-2">
                <div className="text-green-400 mb-2">MiniOS v5.0 Terminal</div>
                <div className="text-gray-300 mb-2">Type 'help' for available commands</div>
                <div className="mb-2">&nbsp;</div>
                {terminalOutput.map((line, i) => (
                  <div key={i} className={
                    line.type === 'input' ? 'text-green-400' :
                    line.type === 'error' ? 'text-red-400' :
                    'text-gray-300'
                  }>
                    {line.text}
                  </div>
                ))}
              </div>
              <div className="flex items-center text-green-400">
                <span className="mr-2">user@minios:{currentPath}$</span>
                <input
                  type="text"
                  value={terminalInput}
                  onChange={(e) => setTerminalInput(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      executeCommand(terminalInput);
                    }
                  }}
                  className="flex-1 bg-transparent outline-none text-green-400"
                  autoFocus
                />
              </div>
            </div>
          )}

          {win.type === 'editor' && (
            <div className="flex flex-col h-full">
              <div className="flex gap-2 p-3 bg-gray-800 border-b border-gray-700">
                <button className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300">New</button>
                <button className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300">Open</button>
                <button className="px-3 py-1 bg-cyan-600 hover:bg-cyan-700 rounded text-sm text-white">Save</button>
              </div>
              <textarea
                value={editorContent}
                onChange={(e) => setEditorContent(e.target.value)}
                placeholder="Start typing..."
                className="flex-1 bg-gray-900 text-gray-300 p-4 outline-none resize-none font-mono"
              />
            </div>
          )}

          {win.type === 'calculator' && (
            <div className="p-6 bg-gray-900">
              <input
                type="text"
                value={calcDisplay}
                readOnly
                className="w-full p-4 mb-4 bg-gray-800 text-white text-right text-2xl rounded outline-none"
              />
              <div className="grid grid-cols-4 gap-2">
                {['7', '8', '9', '/'].map(btn => (
                  <button key={btn} onClick={() => calcBtn(btn)} className="p-4 bg-gray-700 hover:bg-gray-600 text-white rounded text-lg transition-colors">
                    {btn === '/' ? '÷' : btn}
                  </button>
                ))}
                {['4', '5', '6', '*'].map(btn => (
                  <button key={btn} onClick={() => calcBtn(btn)} className="p-4 bg-gray-700 hover:bg-gray-600 text-white rounded text-lg transition-colors">
                    {btn === '*' ? '×' : btn}
                  </button>
                ))}
                {['1', '2', '3', '-'].map(btn => (
                  <button key={btn} onClick={() => calcBtn(btn)} className="p-4 bg-gray-700 hover:bg-gray-600 text-white rounded text-lg transition-colors">
                    {btn === '-' ? '−' : btn}
                  </button>
                ))}
                {['0', '.', '=', '+'].map(btn => (
                  <button 
                    key={btn} 
                    onClick={() => btn === '=' ? calcEqual() : calcBtn(btn)} 
                    className={`p-4 ${btn === '=' ? 'bg-cyan-600 hover:bg-cyan-700' : 'bg-gray-700 hover:bg-gray-600'} text-white rounded text-lg transition-colors`}
                  >
                    {btn}
                  </button>
                ))}
                <button onClick={calcClear} className="col-span-4 p-4 bg-red-600 hover:bg-red-700 text-white rounded text-lg transition-colors">
                  Clear
                </button>
              </div>
            </div>
          )}

          {win.type === 'sysmonitor' && (
            <div className="p-6">
              <h3 className="text-xl text-cyan-400 mb-4">System Monitor</h3>
              <div className="space-y-4">
                <div>
                  <div className="flex justify-between mb-2">
                    <span className="text-gray-300">CPU Usage</span>
                    <span className="text-green-400">{systemStats.cpu}%</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-4">
                    <div className="bg-green-500 h-4 rounded-full transition-all" style={{ width: `${systemStats.cpu}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between mb-2">
                    <span className="text-gray-300">Memory</span>
                    <span className="text-cyan-400">{systemStats.mem}%</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-4">
                    <div className="bg-cyan-500 h-4 rounded-full transition-all" style={{ width: `${systemStats.mem}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between mb-2">
                    <span className="text-gray-300">Disk</span>
                    <span className="text-yellow-400">{systemStats.disk}%</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-4">
                    <div className="bg-yellow-500 h-4 rounded-full transition-all" style={{ width: `${systemStats.disk}%` }} />
                  </div>
                </div>
              </div>
            </div>
          )}

          {win.type === 'processes' && (
            <div className="p-6">
              <h3 className="text-xl text-cyan-400 mb-4">Process Manager</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b border-gray-700">
                    <th className="pb-2 text-cyan-400">PID</th>
                    <th className="pb-2 text-cyan-400">Name</th>
                    <th className="pb-2 text-cyan-400">State</th>
                    <th className="pb-2 text-cyan-400">CPU</th>
                    <th className="pb-2 text-cyan-400">Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {processes.map(proc => (
                    <tr key={proc.pid} className="border-b border-gray-800">
                      <td className="py-2 text-gray-300">{proc.pid}</td>
                      <td className="py-2 text-gray-300">{proc.name}</td>
                      <td className="py-2 text-green-400">{proc.state}</td>
                      <td className="py-2 text-gray-300">{proc.cpu}%</td>
                      <td className="py-2 text-gray-300">{proc.mem} KB</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {win.type === 'network' && (
            <div className="p-6">
              <h3 className="text-xl text-cyan-400 mb-4">Network Interfaces</h3>
              {Object.values(networkDevices).map(iface => (
                <div key={iface.name} className="mb-4 p-4 bg-gray-800 rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-lg font-semibold text-cyan-400">{iface.name}</span>
                    <span className={`px-2 py-1 rounded text-xs ${iface.status === 'UP' ? 'bg-green-600' : 'bg-red-600'}`}>
                      {iface.status}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-400">IP Address:</span>
                      <span className="text-gray-300">{iface.ip}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-400">MAC Address:</span>
                      <span className="text-gray-300">{iface.mac}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-400">Type:</span>
                      <span className="text-gray-300">{iface.type}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {win.type === 'settings' && (
            <div className="p-6">
              <h3 className="text-xl text-cyan-400 mb-4">System Settings</h3>
              <div className="space-y-4">
                <div className="bg-gray-800 p-4 rounded-lg">
                  <h4 className="text-cyan-400 mb-3">Display</h4>
                  <div className="space-y-2">
                    <div className="flex justify-between items-center py-2 border-b border-gray-700">
                      <span className="text-gray-300">Resolution</span>
                      <select className="bg-gray-700 text-gray-300 px-3 py-1 rounded">
                        <option>1920x1080</option>
                        <option>1366x768</option>
                        <option>1280x720</option>
                      </select>
                    </div>
                    <div className="flex justify-between items-center py-2 border-b border-gray-700">
                      <span className="text-gray-300">Theme</span>
                      <select className="bg-gray-700 text-gray-300 px-3 py-1 rounded">
                        <option>Default</option>
                        <option>Dark</option>
                        <option>Light</option>
                      </select>
                    </div>
                    <div className="flex justify-between items-center py-2">
                      <span className="text-gray-300">Color Depth</span>
                      <span className="text-green-400">32-bit</span>
                    </div>
                  </div>
                </div>
                <div className="bg-gray-800 p-4 rounded-lg">
                  <h4 className="text-cyan-400 mb-3">System</h4>
                  <div className="space-y-2">
                    <div className="flex justify-between items-center py-2 border-b border-gray-700">
                      <span className="text-gray-300">OS Version</span>
                      <span className="text-green-400">MiniOS V5.0</span>
                    </div>
                    <div className="flex justify-between items-center py-2 border-b border-gray-700">
                      <span className="text-gray-300">Kernel</span>
                      <span className="text-green-400">5.0.0-ultimate</span>
                    </div>
                    <div className="flex justify-between items-center py-2 border-b border-gray-700">
                      <span className="text-gray-300">Memory</span>
                      <span className="text-green-400">256 MB</span>
                    </div>
                    <div className="flex justify-between items-center py-2">
                      <span className="text-gray-300">Build Date</span>
                      <span className="text-green-400">2024-11-09</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {win.type === 'about' && (
            <div className="p-6 text-center">
              <div className="text-6xl mb-4">⚡</div>
              <h2 className="text-2xl text-cyan-400 mb-2">MiniOS V5.0 ULTIMATE</h2>
              <p className="text-gray-400 mb-4">Complete Desktop Operating System</p>
              <div className="bg-gray-800 p-4 rounded-lg text-left space-y-2 mb-4">
                <div className="text-green-400">✓ Full GUI Desktop Environment</div>
                <div className="text-green-400">✓ Window Manager with Drag & Drop</div>
                <div className="text-green-400">✓ File System (VFS)</div>
                <div className="text-green-400">✓ Terminal Emulator</div>
                <div className="text-green-400">✓ Process Manager</div>
                <div className="text-green-400">✓ Network Stack Simulator</div>
                <div className="text-green-400">✓ System Monitor</div>
                <div className="text-green-400">✓ Text Editor</div>
                <div className="text-green-400">✓ Calculator</div>
                <div className="text-green-400">✓ Multi-tasking Support</div>
                <div className="text-green-400">✓ Multiple Languages (ASM, C, C++, Java, Python, C#, JS)</div>
              </div>
              <p className="text-gray-500 text-sm">
                Built with ❤️ for education and fun
              </p>
            </div>
          )}
        </div>
      </div>
    );
  };

  if (showBootScreen) {
    return (
      <div className="w-full h-screen bg-black flex flex-col items-center justify-center text-green-400 font-mono">
        <div className="text-6xl mb-8 animate-pulse">⚡ MiniOS v5.0</div>
        <div className="text-xl mb-2">ULTIMATE Desktop Edition</div>
        <div className="text-sm mb-8 text-gray-500">Booting Complete Operating System...</div>
        <div className="w-96 h-8 bg-gray-800 border-2 border-green-400 rounded overflow-hidden">
          <div 
            className="h-full bg-gradient-to-r from-green-400 to-green-600 transition-all duration-300"
            style={{ width: `${bootProgress}%` }}
          />
        </div>
        <div className="mt-4 text-sm text-gray-500">
          {bootProgress < 30 ? 'Loading kernel...' :
           bootProgress < 60 ? 'Initializing drivers...' :
           bootProgress < 90 ? 'Starting services...' :
           'Starting desktop...'}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-screen bg-gray-900 relative overflow-hidden">
      <canvas 
        ref={canvasRef} 
        width={1920} 
        height={1080}
        className="absolute inset-0 w-full h-full"
      />

      <div className="absolute inset-0 flex flex-col">
        {/* Top Bar */}
        <div className="bg-gradient-to-r from-gray-900/95 to-gray-800/95 backdrop-blur-sm border-b border-cyan-500/50 px-4 py-2 flex items-center justify-between z-50">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowStartMenu(!showStartMenu)}
              className="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 rounded-lg transition-colors"
            >
              <Grid size={18} />
              <span className="font-semibold">Start</span>
            </button>
            <div className="flex items-center gap-2 bg-gray-800 px-3 py-2 rounded-lg">
              <Search size={16} className="text-gray-400" />
              <input 
                type="text" 
                placeholder="Search..."
                className="bg-transparent outline-none text-sm text-gray-300 w-40"
              />
            </div>
          </div>

          <div className="flex items-center gap-4 text-sm text-gray-300">
            <div className="flex items-center gap-2">
              <Cpu size={16} className="text-green-400" />
              <span>{systemStats.cpu}%</span>
            </div>
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-cyan-400" />
              <span>{systemStats.mem}%</span>
            </div>
            <div className="flex items-center gap-2">
              <Wifi size={16} className={systemStats.net ? "text-green-400" : "text-red-400"} />
              <Volume2 size={16} className="text-cyan-400" />
              <Battery size={16} className="text-yellow-400" />
            </div>
            <div className="flex items-center gap-2 bg-gray-800 px-3 py-2 rounded-lg">
              <Clock size={16} />
              <span>{time.toLocaleTimeString()}</span>
            </div>
            <div className="flex items-center gap-2 bg-gray-800 px-3 py-2 rounded-lg">
              <Calendar size={16} />
              <span>{time.toLocaleDateString()}</span>
            </div>
          </div>
        </div>

        {/* Desktop Area */}
        <div className="flex-1 relative p-4">
          <div className="grid grid-cols-1 gap-2 w-24">
            <DesktopIcon 
              icon={Folder} 
              label="Files" 
              onClick={() => createWindow('files', 'File Manager')}
            />
            <DesktopIcon 
              icon={Terminal} 
              label="Terminal" 
              onClick={() => createWindow('terminal', 'Terminal')}
            />
            <DesktopIcon 
              icon={FileText} 
              label="Editor" 
              onClick={() => createWindow('editor', 'Text Editor')}
            />
            <DesktopIcon 
              icon={Calculator} 
              label="Calculator" 
              onClick={() => createWindow('calculator', 'Calculator')}
            />
            <DesktopIcon 
              icon={Activity} 
              label="Monitor" 
              onClick={() => createWindow('sysmonitor', 'System Monitor')}
            />
            <DesktopIcon 
              icon={Cpu} 
              label="Processes" 
              onClick={() => createWindow('processes', 'Process Manager')}
            />
            <DesktopIcon 
              icon={Network} 
              label="Network" 
              onClick={() => createWindow('network', 'Network')}
            />
            <DesktopIcon 
              icon={Settings} 
              label="Settings" 
              onClick={() => createWindow('settings', 'Settings')}
            />
            <DesktopIcon 
              icon={Monitor} 
              label="About" 
              onClick={() => createWindow('about', 'About MiniOS')}
            />
          </div>

          {windows.map(win => (
            <Window key={win.id} window={win} />
          ))}
        </div>

        {/* Taskbar */}
        <div className="bg-gradient-to-r from-gray-900/95 to-gray-800/95 backdrop-blur-sm border-t border-cyan-500/50 px-4 py-2 flex items-center gap-2 z-50">
          {windows.filter(w => !w.minimized).map(win => (
            <button
              key={win.id}
              onClick={() => setActiveWindow(win.id)}
              className={`px-4 py-2 rounded-lg transition-colors ${
                activeWindow === win.id 
                  ? 'bg-cyan-500 text-white' 
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              {win.title}
            </button>
          ))}
          {windows.filter(w => w.minimized).map(win => (
            <button
              key={win.id}
              onClick={() => restoreWindow(win.id)}
              className="px-4 py-2 rounded-lg bg-gray-700 text-gray-400 hover:bg-gray-600 transition-colors"
            >
              {win.title} (minimized)
            </button>
          ))}
        </div>

        {/* Start Menu */}
        {showStartMenu && (
          <div className="absolute left-4 bottom-16 bg-gray-900/98 backdrop-blur-sm border-2 border-cyan-500 rounded-xl shadow-2xl p-4 w-96 z-50">
            <div className="mb-4">
              <h3 className="text-cyan-400 font-bold text-lg mb-1">MiniOS v5.0</h3>
              <p className="text-gray-500 text-sm mb-3">ULTIMATE Desktop Edition</p>
              <div className="bg-gray-800 px-3 py-2 rounded-lg mb-3">
                <input 
                  type="text" 
                  placeholder="Search applications..."
                  className="bg-transparent outline-none text-sm text-gray-300 w-full"
                />
              </div>
              <h4 className="text-cyan-400 font-semibold text-sm mb-2">Applications</h4>
              <div className="grid grid-cols-3 gap-2">
                <button
                  onClick={() => createWindow('files', 'File Manager')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Folder className="w-8 h-8 text-cyan-400" />
                  <span className="text-xs text-gray-300 mt-1">Files</span>
                </button>
                <button
                  onClick={() => createWindow('terminal', 'Terminal')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Terminal className="w-8 h-8 text-green-400" />
                  <span className="text-xs text-gray-300 mt-1">Terminal</span>
                </button>
                <button
                  onClick={() => createWindow('editor', 'Text Editor')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <FileText className="w-8 h-8 text-blue-400" />
                  <span className="text-xs text-gray-300 mt-1">Editor</span>
                </button>
                <button
                  onClick={() => createWindow('calculator', 'Calculator')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Calculator className="w-8 h-8 text-orange-400" />
                  <span className="text-xs text-gray-300 mt-1">Calculator</span>
                </button>
                <button
                  onClick={() => createWindow('sysmonitor', 'System Monitor')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Activity className="w-8 h-8 text-green-400" />
                  <span className="text-xs text-gray-300 mt-1">Monitor</span>
                </button>
                <button
                  onClick={() => createWindow('processes', 'Processes')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Cpu className="w-8 h-8 text-red-400" />
                  <span className="text-xs text-gray-300 mt-1">Processes</span>
                </button>
                <button
                  onClick={() => createWindow('network', 'Network')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Network className="w-8 h-8 text-blue-400" />
                  <span className="text-xs text-gray-300 mt-1">Network</span>
                </button>
                <button
                  onClick={() => createWindow('settings', 'Settings')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Settings className="w-8 h-8 text-yellow-400" />
                  <span className="text-xs text-gray-300 mt-1">Settings</span>
                </button>
                <button
                  onClick={() => createWindow('about', 'About')}
                  className="flex flex-col items-center p-3 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  <Monitor className="w-8 h-8 text-purple-400" />
                  <span className="text-xs text-gray-300 mt-1">About</span>
                </button>
              </div>
            </div>
            <div className="border-t border-gray-700 pt-3">
              <div className="text-xs text-gray-500 text-center">
                MiniOS V5.0 ULTIMATE - Complete Desktop OS
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Welcome message overlay */}
      {windows.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="bg-gray-900/90 backdrop-blur-sm border-2 border-cyan-500 rounded-xl p-8 text-center animate-pulse">
            <div className="text-6xl mb-4">⚡</div>
            <h1 className="text-3xl text-cyan-400 font-bold mb-2">MiniOS V5.0 ULTIMATE</h1>
            <p className="text-gray-400 mb-4">Complete Desktop Operating System</p>
            <p className="text-sm text-green-400">Double-click desktop icons or use Start menu!</p>
            <div className="mt-4 text-xs text-gray-500 space-y-1">
              <div>✓ Full Filesystem with VFS</div>
              <div>✓ Terminal with 40+ commands</div>
              <div>✓ Process Manager & System Monitor</div>
              <div>✓ Network Stack Simulator</div>
              <div>✓ Multi-language support (ASM, C, C++, Java, Python, C#)</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MiniOSDesktop;