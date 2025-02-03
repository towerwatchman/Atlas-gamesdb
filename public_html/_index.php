<!DOCTYPE html>
<html>

<?php
include 'page/head.php';
$show_images = false;
if (isset($_GET["show_images"])) {
    $show_images = trim($_GET["show_images"]);
}
?>

<body>
    <nav class="navbar navbar-fixed-top">
        <div class="container">
            <div class="navbar-header">
                <button type="button" class="navbar-toggle collapsed" data-toggle="collapse" data-target="#navbar-collapse-main">
                    <span class="sr-only">Toggle navigation</span>
                    <span class="icon-bar"></span>
                    <span class="icon-bar"></span>
                    <span class="icon-bar"></span>
                </button>
                <a class="navbar-brand navbar-brand-gdb" href="/"><img src="Resources/Images/logo.svg"> <span class="title">ATLAS</span><br><span class="subtitle">Games Database</span></a>
            </div>
            <div class="navbar-collapse collapse" id="navbar-collapse-main">
                <ul class="nav navbar-nav">
                    <li><a href="https://www.atlas-gamesdb.com/download" class="orange">Get Atlas</a></li>
                    <!--<li>
                        <a href="javascript:" class="blue dropdown-toggle" data-toggle="dropdown" role="button" aria-haspopup="true" aria-expanded="False">Games DB</a>
                        <ul class="dropdown-menu">
                            <li><a class="blue" href="/">Games</a></li>
                            <li><a class="blue" href="/developers">Developers</a></li>
                            <li role="separator" class="divider"></li>
                            <li><a class="blue" href="/games/search"><i class="fa fa-search" aria-hidden="true"></i> Search</a></li>
                            <li><a class="blue" href="/games/add"><i class="fa fa-plus" aria-hidden="true"></i> Add New Game</a></li>
                        </ul>
                    </li>                   
                        <li><a class="orange" href="/account/sign-in">My Account</a></li>
                    <li><a style="font-size: 16px; padding-top: 23px; padding-bottom: 27px; width: 45px;" class="magenta" href="/games/search"><i class="fa fa-search" aria-hidden="true"></i></a></li>
-->
                </ul>
            </div>
        </div>
    </nav>

    <div class="profile-header text-center">
        <div class="container">
            <div class="container-inner">

                <img class="media-object" src="Resources/Images/logo.svg" alt="Atlas Logo">

                <div class="row">
                    <div class="col-sm-offset-2 col-sm-8">
                        <form role="search">
                            <div class="input-group">
                                <input id="search" type="text" class="form-control" placeholder="Search">
                                <span id="searchButton" class="input-group-addon search-addon"><i class="fa fa-search"></i></span>
                            </div>
                        </form>
                    </div>
                </div>

            </div>
        </div>
        <nav class="profile-header-nav">

            <ul class="nav nav-tabs">
                <li class="active">
                    <a href="/">Games</a>
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

    <div class="container p-t-md">
        <div class="pagination-wrapper">
            <ul class="pagination pagination-lg"></ul>
        </div>

        <?php
        include 'api/config.php';

        $servername = "atlas-gamesdb.com";
        // Create connection 
        $conn = mysqli_connect($servername, $username, $password, $database);
        // Check connection 
        if (!$conn) {
            //die("Connection failed: " . mysqli_connect_error()); 
            $status = 400;
        } else {
            //Output the nav bar first
            $query = mysqli_query($conn, "SELECT COUNT(atlas_id) AS total FROM `atlas` ");
            $result = mysqli_fetch_all($query);
            $rows = $result[0][0];
            $per_page = 25;
            $pages = ceil($rows / $per_page);

            //calculate page start point
            $page = isset($_GET['page']) ? $conn->real_escape_string($_GET['page']) : 0;
            $page == 0 ? $start = 0 : $start = ($page - 1) * $per_page;
            $curpag = ($start == 0) ? 1 : ($start / $per_page) + 1;

            $query = mysqli_query($conn, "SELECT atlas.atlas_id, atlas.title,atlas.creator, atlas.engine, f95_zone.banner_url, atlas.overview FROM `atlas` 
        INNER JOIN f95_zone ON atlas.atlas_id=f95_zone.atlas_id
        ORDER BY atlas.title ASC
        LIMIT $start , $per_page");
            $data = mysqli_fetch_all($query);
            foreach ($data as $item) {
                $atlas_id = $item[0];
                $title =  str_replace("'", '', $item[1]);
                $creator = $item[2];
                $engine = $item[3];
                //$banner_url = $item[4];

                if ($show_images == true) {
                    $banner_url = "<img class=\"img-responsive\" src=" . $item[4] . " alt=" . $title . ">";
                } else {
                    $banner_url = "";
                }
                $overview = $item[5];

                //print($item[1]);

                /*<div class=\"col-sm-2\">
                    <img class=\"img-responsive\" src=" . $banner_url . " alt=" . $title . ">
                </div>*/
                print(" <a class=\"list-item\" href=\"/games/details?id=" . $atlas_id . "\">
                <div class=\"row\">       
                <div class=\"col-sm-2\">
                    " . $banner_url . "
                </div>            
                    <div class=\"col-sm-10\">
                        <h3>" . $title . "</h3>
                        <h5> Developer: " . $creator . "</h5> 
                        <h5> Engine: " . $engine . "</h5> 
                        <p>" . $overview . "
                    </div>
                </div>
            </a>");
            }
        }
        ?>
        <div class="pagination-wrapper">
            <ul class="pagination pagination-lg"></ul>
        </div>

        <script>
            var pages = '<?php echo $pages; ?>'; //We store the number of pages in a variable to use it below
            $('.pagination').twbsPagination({
                totalPages: pages,
                visiblePages: 7,
                href: '?page={{number}}' //Very important!
            });
        </script>


</body>

</html>