<?php
// /api/updates  -  returns the full `updates` table as a JSON array of
// {date, name, md5} for the Atlas client. The client compares these to its
// local update history and downloads any newer .update files from /packages/.
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
if ($query = mysqli_query($conn, "SELECT date, name, md5 FROM updates ORDER BY date DESC")) {
    while ($row = $query->fetch_assoc()) {
        $row['date'] = (int) $row['date'];   // numeric date; name/md5 stay strings
        $result[] = $row;
    }
}
mysqli_close($conn);

echo json_encode($result);
