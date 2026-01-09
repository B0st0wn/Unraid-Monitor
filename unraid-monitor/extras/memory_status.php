<?php
/**
 * Memory Status Script for Unraid Monitor
 *
 * This script reads memory information from /proc/meminfo and calculates
 * the breakdown by System, VM, Docker, and Free memory.
 *
 * Installation:
 *   mkdir -p /usr/local/emhttp/plugins/unraid-monitor
 *   cp memory_status.php /usr/local/emhttp/plugins/unraid-monitor/memory_status.php
 *
 * Endpoint:
 *   https://YOUR_UNRAID_IP/plugins/unraid-monitor/memory_status.php
 */

header('Content-Type: application/json');
header('Cache-Control: no-cache, no-store, must-revalidate');

$result = [
    'timestamp' => time(),
    'version' => '1.0.0',
    'memory' => []
];

/**
 * Parse /proc/meminfo and return memory values in bytes
 */
function parse_meminfo() {
    $meminfo = [];
    $lines = @file('/proc/meminfo');
    if (!$lines) {
        return $meminfo;
    }

    foreach ($lines as $line) {
        if (preg_match('/^(\w+):\s+(\d+)\s*kB?/', $line, $matches)) {
            // Convert kB to bytes
            $meminfo[$matches[1]] = intval($matches[2]) * 1024;
        }
    }
    return $meminfo;
}

/**
 * Get Docker memory usage from cgroups
 */
function get_docker_memory() {
    $docker_mem = 0;

    // Try cgroups v2 first
    $cgroup_v2_path = '/sys/fs/cgroup/system.slice/docker.service/memory.current';
    if (file_exists($cgroup_v2_path)) {
        $docker_mem = intval(trim(@file_get_contents($cgroup_v2_path)));
        if ($docker_mem > 0) {
            return $docker_mem;
        }
    }

    // Try cgroups v1
    $cgroup_v1_path = '/sys/fs/cgroup/memory/docker/memory.usage_in_bytes';
    if (file_exists($cgroup_v1_path)) {
        $docker_mem = intval(trim(@file_get_contents($cgroup_v1_path)));
        if ($docker_mem > 0) {
            return $docker_mem;
        }
    }

    // Alternative: sum up all docker container memory usage
    $docker_cgroup_base = '/sys/fs/cgroup/memory/docker';
    if (is_dir($docker_cgroup_base)) {
        $containers = glob($docker_cgroup_base . '/*/memory.usage_in_bytes');
        foreach ($containers as $mem_file) {
            $container_mem = intval(trim(@file_get_contents($mem_file)));
            $docker_mem += $container_mem;
        }
    }

    return $docker_mem;
}

/**
 * Get VM (libvirt/KVM) memory usage
 */
function get_vm_memory() {
    $vm_mem = 0;

    // Try to get VM memory from libvirt via virsh
    $virsh_output = @shell_exec('virsh list --all 2>/dev/null');
    if ($virsh_output) {
        // Get list of running VMs
        $lines = explode("\n", $virsh_output);
        foreach ($lines as $line) {
            if (preg_match('/^\s*\d+\s+(\S+)\s+running/', $line, $matches)) {
                $vm_name = $matches[1];
                // Get memory for this VM
                $dominfo = @shell_exec("virsh dominfo '$vm_name' 2>/dev/null");
                if ($dominfo && preg_match('/Used memory:\s+(\d+)\s*KiB/i', $dominfo, $mem_match)) {
                    $vm_mem += intval($mem_match[1]) * 1024; // Convert KiB to bytes
                } elseif ($dominfo && preg_match('/Max memory:\s+(\d+)\s*KiB/i', $dominfo, $mem_match)) {
                    // Fallback to max memory if used not available
                    $vm_mem += intval($mem_match[1]) * 1024;
                }
            }
        }
    }

    // Alternative: check qemu processes memory
    if ($vm_mem == 0) {
        $ps_output = @shell_exec("ps aux | grep -E 'qemu|libvirt' | grep -v grep 2>/dev/null");
        if ($ps_output) {
            $lines = explode("\n", trim($ps_output));
            foreach ($lines as $line) {
                $parts = preg_split('/\s+/', $line);
                if (count($parts) >= 6) {
                    // RSS is typically column 6 (0-indexed: 5) in KB
                    $rss_kb = intval($parts[5]);
                    $vm_mem += $rss_kb * 1024;
                }
            }
        }
    }

    return $vm_mem;
}

// Parse /proc/meminfo
$meminfo = parse_meminfo();

if (empty($meminfo)) {
    $result['error'] = 'Could not read /proc/meminfo';
    echo json_encode($result, JSON_PRETTY_PRINT);
    exit;
}

// Calculate memory values
$total = isset($meminfo['MemTotal']) ? $meminfo['MemTotal'] : 0;
$free = isset($meminfo['MemFree']) ? $meminfo['MemFree'] : 0;
$available = isset($meminfo['MemAvailable']) ? $meminfo['MemAvailable'] : 0;
$buffers = isset($meminfo['Buffers']) ? $meminfo['Buffers'] : 0;
$cached = isset($meminfo['Cached']) ? $meminfo['Cached'] : 0;
$slab = isset($meminfo['Slab']) ? $meminfo['Slab'] : 0;
$sreclaimable = isset($meminfo['SReclaimable']) ? $meminfo['SReclaimable'] : 0;

// Get Docker and VM memory
$docker_mem = get_docker_memory();
$vm_mem = get_vm_memory();

// Calculate used memory (total - free - buffers - cached)
$used = $total - $free - $buffers - $cached;
if ($used < 0) {
    $used = $total - $available;
}

// System memory = used - docker - vm
$system_mem = $used - $docker_mem - $vm_mem;
if ($system_mem < 0) {
    $system_mem = 0;
}

// Free memory for the breakdown (what Unraid shows as "Free")
$breakdown_free = $total - $used;
if ($breakdown_free < 0) {
    $breakdown_free = $available;
}

// Build result
$result['memory'] = [
    'total' => $total,
    'total_gib' => round($total / (1024 * 1024 * 1024), 2),
    'used' => $used,
    'used_gib' => round($used / (1024 * 1024 * 1024), 2),
    'free' => $breakdown_free,
    'free_gib' => round($breakdown_free / (1024 * 1024 * 1024), 2),
    'available' => $available,
    'available_gib' => round($available / (1024 * 1024 * 1024), 2),
    'buffers' => $buffers,
    'cached' => $cached,
    'system' => $system_mem,
    'system_gib' => round($system_mem / (1024 * 1024 * 1024), 2),
    'vm' => $vm_mem,
    'vm_gib' => round($vm_mem / (1024 * 1024 * 1024), 2),
    'docker' => $docker_mem,
    'docker_gib' => round($docker_mem / (1024 * 1024 * 1024), 2),
    'percent_used' => $total > 0 ? round(($used / $total) * 100, 1) : 0
];

echo json_encode($result, JSON_PRETTY_PRINT);
