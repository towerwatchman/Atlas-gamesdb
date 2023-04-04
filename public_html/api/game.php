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
$last_record_update = "null";
$games = "null";
$game_count ="null";
//Read in responses if available.
if(isset( $_GET["id"])){$id = "f95_id=".trim($_GET["id"]);}
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
    $base =  "SELECT * FROM f95zone_data";
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
        $query1 = mysqli_query($conn, "SELECT COUNT(title) FROM f95zone_data AS total");
        $query2 = mysqli_query($conn, "SELECT MAX(last_record_update) FROM f95zone_data");
        $game_count = mysqli_fetch_row($query1)[0];
        $last_record_update = mysqli_fetch_row($query2)[0];
        $rows = array();
        while($r = mysqli_fetch_assoc($query)) {
            $rows[] = array("f95_id"=>$r['f95_id'],
                            "title"=>$r['title'],
                            "short_name"=>$r['short_name'],
                            "category"=>$r['category'],
                            "engine"=>$r['engine'],
                            "banner_url"=>$r['banner_url'],
                            "status"=>$r['status'],
                            "version"=>$r['version'],
                            "developer"=>$r['developer'],
                            "site_url"=>$r['site_url'],
                            "overview"=>$r['overview'],
                            "last_thread_update"=>$r['last_thread_update'],
                            "last_release"=>$r['last_release'],
                            "censored"=>$r['censored'],
                            "language"=>explode(",",$r['language']),
                            "translations"=>explode(",",$r['translations']),
                            "length"=>$r['length'],
                            "vndb"=>$r['vndb'],
                            "genre"=>explode(",",$r['genre']),
                            "voice"=>explode(",",$r['voice']),
                            "os"=>explode(",",$r['os']),
                            "views"=>$r['views'],
                            "likes"=>$r['likes'],
                            "replies"=>$r['replies'],                            
                            "tags"=>explode(",",$r['tags']),
                            "rating"=>$r['rating'],
                            "preview_urls"=>explode(",",$r['preview_urls']),
                            "last_record_update"=>$r['last_record_update'],
                            "thread_publish_date"=>$r['thread_publish_date'],
                            "last_thread_comment"=>$r['last_thread_comment']);           
        }
        $status = 200;
        $games = json_encode($rows);
        mysqli_close($conn);
    }   
}
//output JSON
$result = "{\"games\":" . $games . ",\"status\":" . $status.",\"total_games\":".$game_count.",\"last_record_update\":\"".$last_record_update."\"}";
print($result);

//TODO:
//Need to add try catch for db calls. Will error out if wrong input is received
?>