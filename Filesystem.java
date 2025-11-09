// FileSystemSimulator.java - Enhanced Filesystem cho MiniOS v2.0
// Compile: javac FileSystemSimulator.java
// Run: java FileSystemSimulator

import java.util.*;
import java.io.*;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;

// ========== Inode Structure ==========
class Inode {
    private int inodeNumber;
    private String fileName;
    private int fileSize;
    private long createdTime;
    private long modifiedTime;
    private long accessedTime;
    private boolean isDirectory;
    private int permissions;
    private int uid;
    private int gid;
    private int linkCount;
    private List<Integer> dataBlocks;
    private int parentInode;
    private String checksum;
    
    public Inode(int inodeNumber, String fileName, boolean isDirectory, int parentInode) {
        this.inodeNumber = inodeNumber;
        this.fileName = fileName;
        this.fileSize = 0;
        this.createdTime = System.currentTimeMillis();
        this.modifiedTime = this.createdTime;
        this.accessedTime = this.createdTime;
        this.isDirectory = isDirectory;
        this.permissions = isDirectory ? 0755 : 0644;
        this.uid = 0;
        this.gid = 0;
        this.linkCount = 1;
        this.dataBlocks = new ArrayList<>();
        this.parentInode = parentInode;
        this.checksum = "";
    }
    
    // Getters
    public int getInodeNumber() { return inodeNumber; }
    public String getFileName() { return fileName; }
    public int getFileSize() { return fileSize; }
    public long getCreatedTime() { return createdTime; }
    public long getModifiedTime() { return modifiedTime; }
    public long getAccessedTime() { return accessedTime; }
    public boolean isDirectory() { return isDirectory; }
    public int getPermissions() { return permissions; }
    public int getUid() { return uid; }
    public int getGid() { return gid; }
    public int getLinkCount() { return linkCount; }
    public List<Integer> getDataBlocks() { return dataBlocks; }
    public int getParentInode() { return parentInode; }
    public String getChecksum() { return checksum; }
    
    // Setters
    public void setFileSize(int size) { this.fileSize = size; }
    public void setPermissions(int perms) { this.permissions = perms; }
    public void setChecksum(String sum) { this.checksum = sum; }
    public void incrementLinkCount() { linkCount++; }
    public void decrementLinkCount() { linkCount--; }
    
    public void addDataBlock(int blockNumber) {
        dataBlocks.add(blockNumber);
    }
    
    public void updateAccessTime() {
        this.accessedTime = System.currentTimeMillis();
    }
    
    public void updateModifiedTime() {
        this.modifiedTime = System.currentTimeMillis();
        this.accessedTime = this.modifiedTime;
    }
    
    public String getPermissionString() {
        char[] perms = new char[10];
        perms[0] = isDirectory ? 'd' : '-';
        
        int p = permissions;
        perms[1] = (p & 0400) != 0 ? 'r' : '-';
        perms[2] = (p & 0200) != 0 ? 'w' : '-';
        perms[3] = (p & 0100) != 0 ? 'x' : '-';
        perms[4] = (p & 0040) != 0 ? 'r' : '-';
        perms[5] = (p & 0020) != 0 ? 'w' : '-';
        perms[6] = (p & 0010) != 0 ? 'x' : '-';
        perms[7] = (p & 0004) != 0 ? 'r' : '-';
        perms[8] = (p & 0002) != 0 ? 'w' : '-';
        perms[9] = (p & 0001) != 0 ? 'x' : '-';
        
        return new String(perms);
    }
    
    @Override
    public String toString() {
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
        return String.format("%s %3d %4d %4d %8d %s %s",
            getPermissionString(),
            linkCount,
            uid,
            gid,
            fileSize,
            sdf.format(new Date(modifiedTime)),
            fileName);
    }
}

// ========== Data Block ==========
class DataBlock {
    private int blockNumber;
    private byte[] data;
    private static final int BLOCK_SIZE = 4096;
    private boolean dirty;
    
    public DataBlock(int blockNumber) {
        this.blockNumber = blockNumber;
        this.data = new byte[BLOCK_SIZE];
        this.dirty = false;
    }
    
    public int getBlockNumber() { return blockNumber; }
    public byte[] getData() { return data; }
    public boolean isDirty() { return dirty; }
    
    public void writeData(byte[] src, int offset, int length) {
        System.arraycopy(src, 0, data, offset, Math.min(length, BLOCK_SIZE - offset));
        dirty = true;
    }
    
    public void readData(byte[] dest, int offset, int length) {
        System.arraycopy(data, offset, dest, 0, Math.min(length, BLOCK_SIZE - offset));
    }
    
    public void clear() {
        Arrays.fill(data, (byte)0);
        dirty = true;
    }
    
    public void sync() {
        dirty = false;
    }
}

// ========== Directory Entry ==========
class DirectoryEntry {
    private String name;
    private int inodeNumber;
    private byte fileType;
    
    public DirectoryEntry(String name, int inodeNumber, boolean isDir) {
        this.name = name;
        this.inodeNumber = inodeNumber;
        this.fileType = (byte)(isDir ? 1 : 0);
    }
    
    public String getName() { return name; }
    public int getInodeNumber() { return inodeNumber; }
    public boolean isDirectory() { return fileType == 1; }
}

// ========== Superblock ==========
class Superblock {
    private int totalInodes;
    private int totalBlocks;
    private int freeInodes;
    private int freeBlocks;
    private int blockSize;
    private long creationTime;
    private long lastMountTime;
    private int mountCount;
    private String fsLabel;
    
    public Superblock(int totalInodes, int totalBlocks, int blockSize) {
        this.totalInodes = totalInodes;
        this.totalBlocks = totalBlocks;
        this.freeInodes = totalInodes;
        this.freeBlocks = totalBlocks;
        this.blockSize = blockSize;
        this.creationTime = System.currentTimeMillis();
        this.lastMountTime = creationTime;
        this.mountCount = 0;
        this.fsLabel = "MiniOS-FS";
    }
    
    public void allocateInode() { freeInodes--; }
    public void freeInode() { freeInodes++; }
    public void allocateBlock() { freeBlocks--; }
    public void freeBlock() { freeBlocks++; }
    public void mount() { 
        lastMountTime = System.currentTimeMillis();
        mountCount++;
    }
    
    public int getTotalInodes() { return totalInodes; }
    public int getTotalBlocks() { return totalBlocks; }
    public int getFreeInodes() { return freeInodes; }
    public int getFreeBlocks() { return freeBlocks; }
    public int getBlockSize() { return blockSize; }
    
    @Override
    public String toString() {
        return String.format(
            "Filesystem: %s\n" +
            "Total Inodes: %d (Free: %d)\n" +
            "Total Blocks: %d (Free: %d)\n" +
            "Block Size: %d bytes\n" +
            "Mount Count: %d",
            fsLabel, totalInodes, freeInodes, totalBlocks, freeBlocks, blockSize, mountCount
        );
    }
}

// ========== Main FileSystem ==========
public class FileSystemSimulator {
    private Map<Integer, Inode> inodeTable;
    private Map<Integer, DataBlock> dataBlocks;
    private Map<Integer, List<DirectoryEntry>> directories;
    private Superblock superblock;
    private int nextInodeNumber;
    private int nextBlockNumber;
    private int currentDirectory;
    private Set<Integer> openFiles;
    
    private static final int MAX_INODES = 2048;
    private static final int MAX_BLOCKS = 16384;
    private static final int BLOCK_SIZE = 4096;
    
    public FileSystemSimulator() {
        inodeTable = new HashMap<>();
        dataBlocks = new HashMap<>();
        directories = new HashMap<>();
        superblock = new Superblock(MAX_INODES, MAX_BLOCKS, BLOCK_SIZE);
        nextInodeNumber = 0;
        nextBlockNumber = 0;
        currentDirectory = 0;
        openFiles = new HashSet<>();
        
        superblock.mount();
        createDirectory("/", -1);
    }
    
    public int createDirectory(String name, int parentInode) {
        if (nextInodeNumber >= MAX_INODES) {
            System.err.println("Out of inodes!");
            return -1;
        }
        
        Inode inode = new Inode(nextInodeNumber, name, true, parentInode);
        inodeTable.put(nextInodeNumber, inode);
        directories.put(nextInodeNumber, new ArrayList<>());
        
        if (parentInode >= 0) {
            List<DirectoryEntry> parentDir = directories.get(parentInode);
            if (parentDir != null) {
                parentDir.add(new DirectoryEntry(name, nextInodeNumber, true));
                inodeTable.get(parentInode).updateModifiedTime();
            }
        }
        
        superblock.allocateInode();
        return nextInodeNumber++;
    }
    
    public int createFile(String name, int parentInode) {
        if (nextInodeNumber >= MAX_INODES) {
            System.err.println("Out of inodes!");
            return -1;
        }
        
        Inode inode = new Inode(nextInodeNumber, name, false, parentInode);
        inodeTable.put(nextInodeNumber, inode);
        
        List<DirectoryEntry> parentDir = directories.get(parentInode);
        if (parentDir != null) {
            parentDir.add(new DirectoryEntry(name, nextInodeNumber, false));
            inodeTable.get(parentInode).updateModifiedTime();
        }
        
        superblock.allocateInode();
        return nextInodeNumber++;
    }
    
    public boolean writeFile(int inodeNumber, byte[] data) {
        Inode inode = inodeTable.get(inodeNumber);
        if (inode == null || inode.isDirectory()) {
            return false;
        }
        
        // Clear existing blocks
        for (int blockNum : inode.getDataBlocks()) {
            dataBlocks.remove(blockNum);
            superblock.freeBlock();
        }
        inode.getDataBlocks().clear();
        
        int blocksNeeded = (data.length + BLOCK_SIZE - 1) / BLOCK_SIZE;
        
        for (int i = 0; i < blocksNeeded; i++) {
            if (nextBlockNumber >= MAX_BLOCKS) {
                System.err.println("Out of disk space!");
                return false;
            }
            
            DataBlock block = new DataBlock(nextBlockNumber);
            int offset = i * BLOCK_SIZE;
            int length = Math.min(BLOCK_SIZE, data.length - offset);
            block.writeData(data, offset, length);
            
            dataBlocks.put(nextBlockNumber, block);
            inode.addDataBlock(nextBlockNumber);
            superblock.allocateBlock();
            nextBlockNumber++;
        }
        
        inode.setFileSize(data.length);
        inode.updateModifiedTime();
        
        // Calculate checksum
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] hash = md.digest(data);
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            inode.setChecksum(sb.toString());
        } catch (Exception e) {
            // Ignore checksum error
        }
        
        return true;
    }
    
    public byte[] readFile(int inodeNumber) {
        Inode inode = inodeTable.get(inodeNumber);
        if (inode == null || inode.isDirectory()) {
            return null;
        }
        
        inode.updateAccessTime();
        
        byte[] result = new byte[inode.getFileSize()];
        int offset = 0;
        
        for (int blockNum : inode.getDataBlocks()) {
            DataBlock block = dataBlocks.get(blockNum);
            if (block != null) {
                int length = Math.min(BLOCK_SIZE, result.length - offset);
                block.readData(result, offset, length);
                offset += length;
            }
        }
        
        return result;
    }
    
    public boolean deleteFile(int inodeNumber) {
        Inode inode = inodeTable.get(inodeNumber);
        if (inode == null) {
            return false;
        }
        
        if (inode.isDirectory()) {
            List<DirectoryEntry> entries = directories.get(inodeNumber);
            if (entries != null && !entries.isEmpty()) {
                System.err.println("Directory not empty!");
                return false;
            }
            directories.remove(inodeNumber);
        } else {
            // Free data blocks
            for (int blockNum : inode.getDataBlocks()) {
                dataBlocks.remove(blockNum);
                superblock.freeBlock();
            }
        }
        
        // Remove from parent directory
        if (inode.getParentInode() >= 0) {
            List<DirectoryEntry> parentDir = directories.get(inode.getParentInode());
            if (parentDir != null) {
                parentDir.removeIf(entry -> entry.getInodeNumber() == inodeNumber);
                inodeTable.get(inode.getParentInode()).updateModifiedTime();
            }
        }
        
        inodeTable.remove(inodeNumber);
        superblock.freeInode();
        return true;
    }
    
    public void listDirectory(int inodeNumber) {
        List<DirectoryEntry> entries = directories.get(inodeNumber);
        if (entries == null) {
            System.out.println("Not a directory!");
            return;
        }
        
        Inode dirInode = inodeTable.get(inodeNumber);
        System.out.println("Directory: " + dirInode.getFileName());
        System.out.println();
        
        for (DirectoryEntry entry : entries) {
            Inode inode = inodeTable.get(entry.getInodeNumber());
            if (inode != null) {
                System.out.println(inode.toString());
            }
        }
    }
    
    public int findFile(String path) {
        if (path.equals("/")) return 0;
        
        String[] parts = path.split("/");
        int currentInode = 0;
        
        for (String part : parts) {
            if (part.isEmpty()) continue;
            
            List<DirectoryEntry> entries = directories.get(currentInode);
            if (entries == null) return -1;
            
            boolean found = false;
            for (DirectoryEntry entry : entries) {
                if (entry.getName().equals(part)) {
                    currentInode = entry.getInodeNumber();
                    found = true;
                    break;
                }
            }
            
            if (!found) return -1;
        }
        
        return currentInode;
    }
    
    public boolean copyFile(int srcInode, int destParent, String newName) {
        byte[] data = readFile(srcInode);
        if (data == null) return false;
        
        int newInode = createFile(newName, destParent);
        if (newInode < 0) return false;
        
        return writeFile(newInode, data);
    }
    
    public boolean moveFile(int inodeNumber, int newParent) {
        Inode inode = inodeTable.get(inodeNumber);
        if (inode == null) return false;
        
        int oldParent = inode.getParentInode();
        if (oldParent >= 0) {
            List<DirectoryEntry> oldDir = directories.get(oldParent);
            if (oldDir != null) {
                oldDir.removeIf(entry -> entry.getInodeNumber() == inodeNumber);
            }
        }
        
        List<DirectoryEntry> newDir = directories.get(newParent);
        if (newDir != null) {
            newDir.add(new DirectoryEntry(inode.getFileName(), inodeNumber, inode.isDirectory()));
            return true;
        }
        
        return false;
    }
    
    public void printStats() {
        System.out.println("\n╔════════════════════════════════════════════════════════════╗");
        System.out.println("║             MiniOS Filesystem Statistics                  ║");
        System.out.println("╚════════════════════════════════════════════════════════════╝");
        System.out.println();
        System.out.println(superblock);
        System.out.println("Used Space: " + (dataBlocks.size() * BLOCK_SIZE / 1024) + " KB");
        System.out.println("Free Space: " + (superblock.getFreeBlocks() * BLOCK_SIZE / 1024) + " KB");
        System.out.println("Inode Usage: " + ((MAX_INODES - superblock.getFreeInodes()) * 100 / MAX_INODES) + "%");
        System.out.println("Block Usage: " + ((MAX_BLOCKS - superblock.getFreeBlocks()) * 100 / MAX_BLOCKS) + "%");
    }
    
    public void defragment() {
        System.out.println("\n[FS] Starting defragmentation...");
        // Simple defragmentation: compact blocks
        Map<Integer, DataBlock> newBlocks = new HashMap<>();
        int newBlockNum = 0;
        
        for (Inode inode : inodeTable.values()) {
            if (!inode.isDirectory()) {
                List<Integer> newBlockList = new ArrayList<>();
                for (int oldBlock : inode.getDataBlocks()) {
                    DataBlock block = dataBlocks.get(oldBlock);
                    if (block != null) {
                        DataBlock newBlock = new DataBlock(newBlockNum);
                        System.arraycopy(block.getData(), 0, newBlock.getData(), 0, BLOCK_SIZE);
                        newBlocks.put(newBlockNum, newBlock);
                        newBlockList.add(newBlockNum);
                        newBlockNum++;
                    }
                }
                inode.getDataBlocks().clear();
                inode.getDataBlocks().addAll(newBlockList);
            }
        }
        
        dataBlocks = newBlocks;
        nextBlockNumber = newBlockNum;
        System.out.println("[FS] Defragmentation complete. Blocks compacted from scattered to " + newBlockNum);
    }
    
    // Main test method
    public static void main(String[] args) {
        System.out.println("╔════════════════════════════════════════════════════════════╗");
        System.out.println("║        MiniOS Filesystem Simulator v2.0 Enhanced          ║");
        System.out.println("╚════════════════════════════════════════════════════════════╝");
        System.out.println();
        
        FileSystemSimulator fs = new FileSystemSimulator();
        
        // Create directory structure
        System.out.println("[FS] Creating directory structure...");
        int bin = fs.createDirectory("bin", 0);
        int etc = fs.createDirectory("etc", 0);
        int home = fs.createDirectory("home", 0);
        int usr = fs.createDirectory("usr", 0);
        int dev = fs.createDirectory("dev", 0);
        int tmp = fs.createDirectory("tmp", 0);
        
        // Create subdirectories
        int usrBin = fs.createDirectory("bin", usr);
        int usrLib = fs.createDirectory("lib", usr);
        int homeUser = fs.createDirectory("user", home);
        
        // Create files
        System.out.println("[FS] Creating files...");
        int readme = fs.createFile("README.md", 0);
        String readmeContent = "# MiniOS v2.0\n\nWelcome to MiniOS Enhanced!\n\n" +
                              "This is an advanced educational operating system.\n\n" +
                              "Features:\n- Memory Management\n- Process Scheduling\n" +
                              "- Filesystem\n- Network Stack\n";
        fs.writeFile(readme, readmeContent.getBytes());
        
        int config = fs.createFile("config.sys", etc);
        String configContent = "# MiniOS Configuration\n" +
                              "KERNEL_MODE=protected\n" +
                              "MEMORY_SIZE=256MB\n" +
                              "FILESYSTEM=ext2\n" +
                              "DEVICE_DRIVERS=keyboard,disk,timer,rtc\n";
        fs.writeFile(config, configContent.getBytes());
        
        int bootScript = fs.createFile("boot.sh", etc);
        String bootContent = "#!/bin/sh\n" +
                            "echo \"Booting MiniOS...\"\n" +
                            "init_drivers\n" +
                            "mount_filesystem /\n" +
                            "start_services\n";
        fs.writeFile(bootScript, bootContent.getBytes());
        
        // Demo file operations
        System.out.println("\n[FS] Listing root directory:");
        fs.listDirectory(0);
        
        System.out.println("\n[FS] Listing /etc directory:");
        fs.listDirectory(etc);
        
        System.out.println("\n[FS] Reading README.md:");
        byte[] data = fs.readFile(readme);
        if (data != null) {
            System.out.println(new String(data));
        }
        
        // Copy file
        System.out.println("\n[FS] Copying README.md to /home/user/");
        fs.copyFile(readme, homeUser, "README_copy.md");
        
        System.out.println("\n[FS] Listing /home/user:");
        fs.listDirectory(homeUser);
        
        // Statistics
        fs.printStats();
        
        // Defragment
        fs.defragment();
        
        System.out.println("\n[FS] Filesystem operations completed successfully!");
    }
}