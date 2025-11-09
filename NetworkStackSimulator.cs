// NetworkStackSimulator.cs - Mô phỏng Network Stack cho MiniOS
// Compile: csc NetworkStackSimulator.cs
// hoặc: dotnet run NetworkStackSimulator.cs

using System;
using System.Collections.Generic;
using System.Text;
using System.Linq;
using System.Threading;

namespace MiniOS.Network
{
    // Ethernet Frame
    public class EthernetFrame
    {
        public byte[] DestinationMAC { get; set; }
        public byte[] SourceMAC { get; set; }
        public ushort EtherType { get; set; }
        public byte[] Payload { get; set; }
        
        public EthernetFrame()
        {
            DestinationMAC = new byte[6];
            SourceMAC = new byte[6];
            Payload = new byte[0];
        }
        
        public static string MACToString(byte[] mac)
        {
            return string.Join(":", mac.Select(b => b.ToString("X2")));
        }
        
        public override string ToString()
        {
            return $"ETH: {MACToString(SourceMAC)} -> {MACToString(DestinationMAC)} Type: 0x{EtherType:X4}";
        }
    }
    
    // IP Packet
    public class IPPacket
    {
        public byte Version { get; set; }
        public byte HeaderLength { get; set; }
        public byte Protocol { get; set; }
        public uint SourceIP { get; set; }
        public uint DestinationIP { get; set; }
        public byte[] Payload { get; set; }
        
        public IPPacket()
        {
            Version = 4;
            HeaderLength = 20;
            Payload = new byte[0];
        }
        
        public static string IPToString(uint ip)
        {
            return $"{(ip >> 24) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 8) & 0xFF}.{ip & 0xFF}";
        }
        
        public override string ToString()
        {
            return $"IP: {IPToString(SourceIP)} -> {IPToString(DestinationIP)} Proto: {Protocol}";
        }
    }
    
    // TCP Segment
    public class TCPSegment
    {
        public ushort SourcePort { get; set; }
        public ushort DestinationPort { get; set; }
        public uint SequenceNumber { get; set; }
        public uint AcknowledgmentNumber { get; set; }
        public byte Flags { get; set; }
        public ushort WindowSize { get; set; }
        public byte[] Data { get; set; }
        
        // TCP Flags
        public const byte FIN = 0x01;
        public const byte SYN = 0x02;
        public const byte RST = 0x04;
        public const byte PSH = 0x08;
        public const byte ACK = 0x10;
        
        public TCPSegment()
        {
            WindowSize = 65535;
            Data = new byte[0];
        }
        
        public override string ToString()
        {
            string flags = "";
            if ((Flags & SYN) != 0) flags += "SYN ";
            if ((Flags & ACK) != 0) flags += "ACK ";
            if ((Flags & FIN) != 0) flags += "FIN ";
            if ((Flags & PSH) != 0) flags += "PSH ";
            if ((Flags & RST) != 0) flags += "RST ";
            
            return $"TCP: {SourcePort} -> {DestinationPort} [{flags.TrimEnd()}] Seq: {SequenceNumber}";
        }
    }
    
    // Socket
    public class Socket
    {
        public int SocketID { get; set; }
        public uint LocalIP { get; set; }
        public ushort LocalPort { get; set; }
        public uint RemoteIP { get; set; }
        public ushort RemotePort { get; set; }
        public string State { get; set; }
        
        public Socket(int id)
        {
            SocketID = id;
            State = "CLOSED";
        }
        
        public override string ToString()
        {
            return $"Socket {SocketID}: {IPPacket.IPToString(LocalIP)}:{LocalPort} -> " +
                   $"{IPPacket.IPToString(RemoteIP)}:{RemotePort} [{State}]";
        }
    }
    
    // Network Interface
    public class NetworkInterface
    {
        public string Name { get; set; }
        public byte[] MACAddress { get; set; }
        public uint IPAddress { get; set; }
        public uint SubnetMask { get; set; }
        public uint Gateway { get; set; }
        public bool IsUp { get; set; }
        
        private Queue<EthernetFrame> rxQueue;
        private Queue<EthernetFrame> txQueue;
        
        public NetworkInterface(string name)
        {
            Name = name;
            MACAddress = new byte[6];
            rxQueue = new Queue<EthernetFrame>();
            txQueue = new Queue<EthernetFrame>();
            IsUp = false;
            
            // Generate random MAC
            Random rand = new Random();
            rand.NextBytes(MACAddress);
            MACAddress[0] = (byte)((MACAddress[0] & 0xFE) | 0x02); // Local MAC
        }
        
        public void BringUp()
        {
            IsUp = true;
            Console.WriteLine($"[NET] Interface {Name} is UP");
        }
        
        public void BringDown()
        {
            IsUp = false;
            Console.WriteLine($"[NET] Interface {Name} is DOWN");
        }
        
        public void SendFrame(EthernetFrame frame)
        {
            if (!IsUp) return;
            txQueue.Enqueue(frame);
        }
        
        public EthernetFrame ReceiveFrame()
        {
            if (rxQueue.Count > 0)
                return rxQueue.Dequeue();
            return null;
        }
        
        public void SimulateReceive(EthernetFrame frame)
        {
            if (IsUp)
                rxQueue.Enqueue(frame);
        }
        
        public override string ToString()
        {
            string status = IsUp ? "UP" : "DOWN";
            return $"{Name}: MAC: {EthernetFrame.MACToString(MACAddress)} " +
                   $"IP: {IPPacket.IPToString(IPAddress)}/{IPPacket.IPToString(SubnetMask)} [{status}]";
        }
    }
    
    // Network Stack
    public class NetworkStack
    {
        private List<NetworkInterface> interfaces;
        private List<Socket> sockets;
        private int nextSocketID;
        private Dictionary<ushort, Socket> portBindings;
        
        public NetworkStack()
        {
            interfaces = new List<NetworkInterface>();
            sockets = new List<Socket>();
            nextSocketID = 1;
            portBindings = new Dictionary<ushort, Socket>();
        }
        
        public NetworkInterface CreateInterface(string name)
        {
            var iface = new NetworkInterface(name);
            interfaces.Add(iface);
            return iface;
        }
        
        public Socket CreateSocket()
        {
            var socket = new Socket(nextSocketID++);
            sockets.Add(socket);
            return socket;
        }
        
        public bool BindSocket(Socket socket, uint ip, ushort port)
        {
            if (portBindings.ContainsKey(port))
                return false;
            
            socket.LocalIP = ip;
            socket.LocalPort = port;
            portBindings[port] = socket;
            socket.State = "BOUND";
            return true;
        }
        
        public bool ConnectSocket(Socket socket, uint remoteIP, ushort remotePort)
        {
            socket.RemoteIP = remoteIP;
            socket.RemotePort = remotePort;
            socket.State = "SYN_SENT";
            
            // Simulate TCP handshake
            SimulateTCPHandshake(socket);
            
            return true;
        }
        
        private void SimulateTCPHandshake(Socket socket)
        {
            Console.WriteLine($"[TCP] Starting handshake for socket {socket.SocketID}");
            
            // SYN
            var syn = new TCPSegment
            {
                SourcePort = socket.LocalPort,
                DestinationPort = socket.RemotePort,
                Flags = TCPSegment.SYN,
                SequenceNumber = (uint)new Random().Next()
            };
            Console.WriteLine($"[TCP] Sent: {syn}");
            
            Thread.Sleep(10);
            
            // SYN-ACK (simulated)
            Console.WriteLine($"[TCP] Received: SYN-ACK");
            socket.State = "SYN_RECEIVED";
            
            Thread.Sleep(10);
            
            // ACK
            var ack = new TCPSegment
            {
                SourcePort = socket.LocalPort,
                DestinationPort = socket.RemotePort,
                Flags = TCPSegment.ACK,
                SequenceNumber = syn.SequenceNumber + 1,
                AcknowledgmentNumber = syn.SequenceNumber + 1
            };
            Console.WriteLine($"[TCP] Sent: {ack}");
            
            socket.State = "ESTABLISHED";
            Console.WriteLine($"[TCP] Connection established for socket {socket.SocketID}");
        }
        
        public void SendData(Socket socket, byte[] data)
        {
            if (socket.State != "ESTABLISHED")
            {
                Console.WriteLine($"[TCP] Socket {socket.SocketID} not connected");
                return;
            }
            
            var segment = new TCPSegment
            {
                SourcePort = socket.LocalPort,
                DestinationPort = socket.RemotePort,
                Flags = TCPSegment.PSH | TCPSegment.ACK,
                Data = data
            };
            
            Console.WriteLine($"[TCP] Sending {data.Length} bytes: {segment}");
        }
        
        public void CloseSocket(Socket socket)
        {
            socket.State = "FIN_WAIT";
            
            var fin = new TCPSegment
            {
                SourcePort = socket.LocalPort,
                DestinationPort = socket.RemotePort,
                Flags = TCPSegment.FIN | TCPSegment.ACK
            };
            
            Console.WriteLine($"[TCP] Closing connection: {fin}");
            
            Thread.Sleep(10);
            socket.State = "CLOSED";
            
            if (portBindings.ContainsKey(socket.LocalPort))
                portBindings.Remove(socket.LocalPort);
        }
        
        public void DisplayInterfaces()
        {
            Console.WriteLine("\n=== Network Interfaces ===");
            foreach (var iface in interfaces)
            {
                Console.WriteLine(iface);
            }
        }
        
        public void DisplaySockets()
        {
            Console.WriteLine("\n=== Active Sockets ===");
            foreach (var socket in sockets)
            {
                Console.WriteLine(socket);
            }
        }
        
        public void DisplayRouting()
        {
            Console.WriteLine("\n=== Routing Table ===");
            Console.WriteLine("Destination     Gateway         Netmask         Interface");
            Console.WriteLine("---------------------------------------------------------------");
            
            foreach (var iface in interfaces)
            {
                if (iface.IsUp)
                {
                    Console.WriteLine($"{IPPacket.IPToString(iface.IPAddress & iface.SubnetMask),-15} " +
                                    $"{IPPacket.IPToString(0),-15} " +
                                    $"{IPPacket.IPToString(iface.SubnetMask),-15} {iface.Name}");
                }
            }
        }
    }
    
    // Main Program
    class Program
    {
        static uint ParseIP(string ip)
        {
            var parts = ip.Split('.');
            return ((uint)byte.Parse(parts[0]) << 24) |
                   ((uint)byte.Parse(parts[1]) << 16) |
                   ((uint)byte.Parse(parts[2]) << 8) |
                   (uint)byte.Parse(parts[3]);
        }
        
        static void Main(string[] args)
        {
            Console.WriteLine("╔════════════════════════════════════════════════════════════╗");
            Console.WriteLine("║       MiniOS Network Stack Simulator v1.0                  ║");
            Console.WriteLine("╚════════════════════════════════════════════════════════════╝");
            Console.WriteLine();
            
            var netStack = new NetworkStack();
            
            // Create and configure network interface
            Console.WriteLine("[NET] Initializing network stack...");
            var eth0 = netStack.CreateInterface("eth0");
            eth0.IPAddress = ParseIP("192.168.1.100");
            eth0.SubnetMask = ParseIP("255.255.255.0");
            eth0.Gateway = ParseIP("192.168.1.1");
            eth0.BringUp();
            
            netStack.DisplayInterfaces();
            netStack.DisplayRouting();
            
            // Create and test socket
            Console.WriteLine("\n[NET] Creating socket...");
            var socket = netStack.CreateSocket();
            
            Console.WriteLine("[NET] Binding socket to 192.168.1.100:8080");
            netStack.BindSocket(socket, eth0.IPAddress, 8080);
            
            Console.WriteLine("\n[NET] Connecting to 192.168.1.50:80");
            netStack.ConnectSocket(socket, ParseIP("192.168.1.50"), 80);
            
            netStack.DisplaySockets();
            
            // Send data
            Console.WriteLine("\n[NET] Sending HTTP request...");
            string httpRequest = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n";
            netStack.SendData(socket, Encoding.ASCII.GetBytes(httpRequest));
            
            Thread.Sleep(100);
            
            // Close socket
            Console.WriteLine("\n[NET] Closing socket...");
            netStack.CloseSocket(socket);
            
            netStack.DisplaySockets();
            
            // Statistics
            Console.WriteLine("\n=== Network Statistics ===");
            Console.WriteLine("Total Interfaces: 1");
            Console.WriteLine("Total Sockets: 1");
            Console.WriteLine("Packets Sent: 4 (SYN, ACK, DATA, FIN)");
            Console.WriteLine("Packets Received: 1 (SYN-ACK)");
            
            Console.WriteLine("\n[NET] Network stack demonstration complete!");
        }
    }
}