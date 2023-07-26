<!DOCTYPE html>

<html>
<?php
include '../page/head.php';
if (isset($_GET["id"])) {
    $id = trim($_GET["id"]);
}
?>

<body>
    <?php
    include '../page/nav.php';
    ?>



    <?php
    include '../api/config.php';

    $servername = "atlas-gamesdb.com";
    // Create connection 
    $conn = mysqli_connect($servername, $username, $password, $database);
    // Check connection 
    if (!$conn) {
        //die("Connection failed: " . mysqli_connect_error()); 
        $status = 400;
    } else {
        //print($id);
        $query = mysqli_query($conn, "SELECT * FROM `atlas` WHERE atlas_id =  '" . $id . " '");
        //$f95query = mysqli_query($conn, "SELECT * FROM `f95_zone_data` WHERE atlas_id =  '" . $id . " '");

        $data = mysqli_fetch_all($query);
        $atlas_fields = mysqli_fetch_assoc($query);
        //$f95_data = mysqli_fetch_all($query);
        $columns = array();
        if (!empty($data)) {
            $columns = array_keys($data[0]);
        }

        $title =  str_replace("'", '', $data[0][3]);
        $overview = $data[0][11];
        print_r($atlas_fields);
    }
    /*<img class="header-art" src="https://images.launchbox-app.com/1cd45aa5-79d6-44a3-86a9-65ea92662f98.jpg" alt="20th Century Video Almanac">*/
    echo ("<div class=\"profile-header text-center\">
        <div class=\"container\">
        <div class=\"container-inner\">");
    echo ("<h3 class=\"profile-header-user\">" . $title . "</h3>");
    echo ("<p class=\"profile-header-bio\" style=\"margin-top: 20px;\"></p>");
    echo ("</div></div>");

    ?>

    <nav class="profile-header-nav">

        <ul class="nav nav-tabs">
            <li class="active">
                <a href="/">Details</a>
            </li>
            <!--<li>
            <a href="/developers">Developers</a>
        </li>
        <li>
            <a href="/genres">Genres</a>
        </li>
        <li>
            <a href="/games/add">Add New Game</a>
        </li>-->
        </ul>
    </nav>
    </div>
    <?php
    //print_r($data);
    echo ("<div class=\"container p-t-md\">");
    echo "<table class=\"table table-striped table-bordered table-hover table-details\">";
    echo ("<tbody>");
    foreach ($data as $values) {
        foreach ($values as
            $key => $item) {
            echo "<tr>";
            echo ("<td class=\"row-header\">" . $columns[$key] . "</td>");
            echo "<td>";
            if ($item != NULL) {
                print_r($item);
            }

            echo "</td></tr>";
        }
    }

    echo ("</tbody></table></div>");
    ?>

</body>

</html>