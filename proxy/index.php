<?php

// 1. Get the target URL from the '_' parameter
$targetUrl = isset($_GET['_']) ? $_GET['_'] : null;

if (!$targetUrl || !filter_var($targetUrl, FILTER_VALIDATE_URL)) {
    header("HTTP/1.1 400 Bad Request");
    die("Error: Missing or invalid target URL in '_' parameter.");
}

// 2. Initialize cURL
$ch = curl_init($targetUrl);

// 3. Capture and forward all request headers (except host)
$requestHeaders = [];
foreach (getallheaders() as $key => $value) {
    if (strtolower($key) !== 'host') {
        $requestHeaders[] = "$key: $value";
    }
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $requestHeaders);

// 4. Preserve request method and body (for POST, PUT, etc.)
$method = $_SERVER['REQUEST_METHOD'];
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);

if ($method !== 'GET' && $method !== 'HEAD') {
    $input = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $input);
}

// 5. Essential proxy settings
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true); // Get headers from target to pass back
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true); // Follow redirects automatically
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false); // Ignore SSL errors for retro compatibility
curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);

// 6. Execute and split response
$response = curl_exec($ch);
$headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$headerContent = substr($response, 0, $headerSize);
$bodyContent = substr($response, $headerSize);

if (curl_errno($ch)) {
    header("HTTP/1.1 502 Bad Gateway");
    die("Proxy Error: " . curl_error($ch));
}
curl_close($ch);

// 7. Pass target response headers back to the client
$headers = explode("\r\n", $headerContent);
foreach ($headers as $header) {
    if (!empty($header) && strpos($header, 'Transfer-Encoding') === false) {
        header($header);
    }
}

// 8. Output the final body
echo $bodyContent;
