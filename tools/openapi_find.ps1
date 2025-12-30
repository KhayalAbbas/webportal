# PowerShell script to download OpenAPI spec and search for keywords
param([string]$keyword = "")

$url = "http://localhost:8005/openapi.json"
try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing
    $openapi = $response.Content | ConvertFrom-Json
    
    if ($keyword) {
        Write-Host "Searching OpenAPI spec for: $keyword"
        Write-Host "=" * 50
        
        # Search in paths
        foreach ($path in $openapi.paths.PSObject.Properties) {
            if ($path.Name -match $keyword -or $path.Value.ToString() -match $keyword) {
                Write-Host "PATH: $($path.Name)"
                foreach ($method in $path.Value.PSObject.Properties) {
                    Write-Host "  $($method.Name.ToUpper()): $($method.Value.summary)"
                }
            }
        }
    } else {
        # Just output the raw JSON
        $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
    }
} catch {
    Write-Host "Error fetching OpenAPI spec: $($_.Exception.Message)"
    exit 1
}