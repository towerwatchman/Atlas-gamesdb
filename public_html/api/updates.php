<?php
//towerwatchman 3/28/2023

include 'config.php';
//Set header type. 
header('Content-Type: application/json'); 
// Create connection 
$conn = mysqli_connect($servername, $username, $password, $database); 
// Check connection 
if (!$conn) { 
    //die("Connection failed: " . mysqli_connect_error()); 
    $status = 400;
}
else{
    $query = mysqli_query($conn, "SELECT * FROM updates ORDER BY date DESC");

    while($row = $query->fetch_assoc()) {
        $result[] = $row;
    }
    $json = json_encode($result, JSON_NUMERIC_CHECK );
    mysqli_close($conn);
    print($json);
}