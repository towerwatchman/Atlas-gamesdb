<?php
// /api/updates  -  returns the full `updates` table as a JSON array of
// {date, name, md5, full} for the Atlas client. The client compares these
// to its local update history and downloads any newer .update files from
// /packages/. The `full` boolean tells the client whether a package
// contains the complete dataset (true) or only records updated since the
// last run (false / snapshot).
//
// Served via an Apache Alias:  Alias /api/updates /var/www/html/api/updates.php
// Uses a READ-ONLY MySQL user; credentials live outside the web root.

require '/etc/atlas/config.php';   // defines $servername,$username,$password,$database

header('Content-Type: application/json');

$conn = mysqli_connect($servername, $username, $password, $database);
if (!$conn) {
    http_response_code(500);
    echo json_encode(['error' => 'database connection failed']);
    exit;
}

$result = [];   // ensure an empty table returns [] (a valid JSON array), not null
if ($query = mysqli_query($conn, "SELECT date, name, md5, is_full FROM updates ORDER BY date DESC")) {
    while ($row = $query->fetch_assoc()) {
        $row['date']    = (int) $row['date'];        // numeric epoch
        $row['is_full'] = (bool) $row['is_full'];    // tinyint -> JSON true/false
        $result[] = $row;
    }
}
mysqli_close($conn);

echo json_encode($result);
