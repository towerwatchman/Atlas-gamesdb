<?php
//towerwatchman 3/28/2023

include 'config.php';
//Set header type. 
header('Content-Type: application/json'); 
//Set Local VARS.
$id = "";
$title = "";
$version = "";
$developer = "";
$status = 200;
$last_record_update = NULL;
$games = NULL;
$game_count = NULL;
//Read in responses if available.
if(isset( $_GET["id"])){$id = "id=".trim($_GET["id"]);}
if(isset( $_GET["title"])){$title = "title=".trim($_GET["title"]);}
if(isset( $_GET["version"])){$version = "version=".trim($_GET["version"]);}
if(isset( $_GET["creator"])){$developer = "developer=".trim($_GET["creator"]);}

//All vars for server are pulled from config.php
//This is not stored in git. 

// Create connection 
$conn = mysqli_connect($servername, $username, $password, $database); 
// Check connection 
if (!$conn) { 
    //die("Connection failed: " . mysqli_connect_error()); 
    $status = 400;
}
else{
    //verify we have an input
    $base =  "SELECT * FROM atlas";
    $query1 = mysqli_query($conn, "SELECT COUNT(title) FROM atlas AS total");
    $query2 = mysqli_query($conn, "SELECT MAX(last_db_update) FROM atlas");
    $game_count = mysqli_fetch_row($query1)[0];
    $last_db_update = mysqli_fetch_row($query2)[0];

    if($title != "" | $id != "" | $version != "" | $developer != "") 
    {
       
        if($id != "")
        {
            $base = $base." WHERE ".$id;            
        }
        else if($title !=""){
            $base = $base." WHERE ".$title;
        }
        else if($developer != ""){
            $base = $base." WHERE ".$developer;
        }

        $query = mysqli_query($conn, $base);
        
        $tmp = mysqli_fetch_assoc($query);
        
        //Get f95 data if there is any

        $query3 = mysqli_query($conn, "SELECT * FROM f95_zone_data WHERE id=".$tmp["id"]);

        //print("SELECT * FROM f95_zone_data WHERE id= " .$tmp["id"]);

        $f95 = mysqli_fetch_all($query3);
        
        
        $tmp["f95"] = $f95;
        
        
        $games = json_encode($tmp);
        //print($f95);
        $status = 200;

        mysqli_close($conn);
    }   
}
//output JSON
if($games == "")
{
    $games = "[]";
};

$result = "{\"games\":" . $games . ",\"status\":" . $status.",\"total_games\":".$game_count.",\"last_db_update\":\"".$last_db_update."\"}";
print($result);

//TODO:
//Need to add try catch for db calls. Will error out if wrong input is received
?>