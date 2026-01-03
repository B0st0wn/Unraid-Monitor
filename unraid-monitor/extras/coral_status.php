<?php
/**
 * Coral TPU Status Script for Unraid Monitor
 *
 * This script reads Coral TPU device information from sysfs and lsusb,
 * returning JSON data for the Unraid Monitor collector.
 *
 * Installation Options:
 *
 * 1. Copy to Unraid plugins directory (recommended):
 *    cp coral_status.php /usr/local/emhttp/plugins/dynamix/coral_status.php
 *
 * 2. Or create a simple plugin structure:
 *    mkdir -p /usr/local/emhttp/plugins/coral
 *    cp coral_status.php /usr/local/emhttp/plugins/coral/coral_status.php
 *
 * 3. Or use User Scripts plugin to output to /state/:
 *    Save output to: /usr/local/emhttp/state/coral_status.json
 *
 * After installation, the endpoint will be accessible at:
 *    https://your-unraid-ip/plugins/dynamix/coral_status.php
 *    or https://your-unraid-ip/plugins/coral/coral_status.php
 *    or https://your-unraid-ip/state/coral_status.json
 */

header('Content-Type: application/json');
header('Cache-Control: no-cache, no-store, must-revalidate');

$result = [
    'pcie' => [],
    'usb' => [],
    'timestamp' => time(),
    'version' => '1.0.0'
];

/**
 * Scan for PCIe/M.2 Coral TPU devices via sysfs
 */
$apex_base = '/sys/class/apex';
if (is_dir($apex_base)) {
    $apex_devices = glob($apex_base . '/apex_*');

    foreach ($apex_devices as $apex_path) {
        $id = basename($apex_path);
        $device_num = str_replace('apex_', '', $id);

        $device_data = [
            'id' => $id,
            'device' => "/dev/apex{$device_num}",
            'available' => file_exists("/dev/apex{$device_num}")
        ];

        // Read temperature (in millidegrees Celsius)
        $temp_file = "{$apex_path}/temp";
        if (file_exists($temp_file) && is_readable($temp_file)) {
            $temp_raw = @file_get_contents($temp_file);
            if ($temp_raw !== false) {
                $temp_milli = intval(trim($temp_raw));
                $device_data['temp'] = $temp_milli;
                $device_data['temp_c'] = round($temp_milli / 1000, 1);
            }
        }

        // Read trip points (thermal throttling thresholds)
        // trip_point0: 250 MHz throttle (default 85C)
        // trip_point1: 125 MHz throttle (default 90C)
        // trip_point2: 62.5 MHz throttle (default 95C)
        for ($i = 0; $i <= 2; $i++) {
            $tp_file = "{$apex_path}/trip_point{$i}_temp";
            if (file_exists($tp_file) && is_readable($tp_file)) {
                $tp_raw = @file_get_contents($tp_file);
                if ($tp_raw !== false) {
                    $device_data["trip_point{$i}"] = intval(trim($tp_raw));
                }
            }
        }

        // Read hardware shutdown temperature (default 100C)
        $shutdown_file = "{$apex_path}/hw_temp_warn2";
        if (file_exists($shutdown_file) && is_readable($shutdown_file)) {
            $shutdown_raw = @file_get_contents($shutdown_file);
            if ($shutdown_raw !== false) {
                $device_data['shutdown_temp'] = intval(trim($shutdown_raw));
            }
        }

        // Read temperature poll interval (in milliseconds)
        $poll_file = "{$apex_path}/temp_poll_interval";
        if (file_exists($poll_file) && is_readable($poll_file)) {
            $poll_raw = @file_get_contents($poll_file);
            if ($poll_raw !== false) {
                $device_data['poll_interval'] = intval(trim($poll_raw));
            }
        }

        // Calculate current throttle state based on temperature
        $temp = isset($device_data['temp']) ? $device_data['temp'] : 0;
        $tp0 = isset($device_data['trip_point0']) ? $device_data['trip_point0'] : 85000;
        $tp1 = isset($device_data['trip_point1']) ? $device_data['trip_point1'] : 90000;
        $tp2 = isset($device_data['trip_point2']) ? $device_data['trip_point2'] : 95000;
        $shutdown = isset($device_data['shutdown_temp']) ? $device_data['shutdown_temp'] : 100000;

        if ($temp >= $shutdown) {
            $device_data['throttle_state'] = 'shutdown_risk';
        } elseif ($temp >= $tp2) {
            $device_data['throttle_state'] = 'throttled_62';
        } elseif ($temp >= $tp1) {
            $device_data['throttle_state'] = 'throttled_125';
        } elseif ($temp >= $tp0) {
            $device_data['throttle_state'] = 'throttled_250';
        } else {
            $device_data['throttle_state'] = 'normal';
        }

        $result['pcie'][] = $device_data;
    }
}

/**
 * Scan for USB Coral TPU devices via lsusb
 *
 * Coral USB device IDs:
 *   - 1a6e:089a = Global Unichip Corp. (uninitialized state)
 *   - 18d1:9302 = Google Inc. (initialized/ready state)
 */
$lsusb_output = @shell_exec('lsusb 2>/dev/null');
if ($lsusb_output) {
    $lines = explode("\n", trim($lsusb_output));
    $usb_index = 0;

    foreach ($lines as $line) {
        // Match both uninitialized and initialized Coral USB devices
        // Format: "Bus 001 Device 004: ID 18d1:9302 Google Inc."
        if (preg_match('/Bus (\d+) Device (\d+):.*ID (1a6e:089a|18d1:9302)/', $line, $matches)) {
            $vendor_product = $matches[3];
            $parts = explode(':', $vendor_product);

            $result['usb'][] = [
                'id' => "usb_coral_{$usb_index}",
                'bus' => $matches[1],
                'device' => $matches[2],
                'vendor_id' => $parts[0],
                'product_id' => $parts[1],
                'initialized' => ($vendor_product === '18d1:9302'),
                'description' => ($vendor_product === '18d1:9302')
                    ? 'Google Coral USB Accelerator (Ready)'
                    : 'Google Coral USB Accelerator (Not Initialized)'
            ];
            $usb_index++;
        }
    }
}

// Add summary counts
$result['summary'] = [
    'total_devices' => count($result['pcie']) + count($result['usb']),
    'pcie_count' => count($result['pcie']),
    'usb_count' => count($result['usb'])
];

echo json_encode($result, JSON_PRETTY_PRINT);
