param()
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$targetDirectory = Join-Path $workspace 'frontend/public/assets/surfaces'
New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
# Only download the nine selected CC0 files; no recursive site crawl.
foreach ($asset in @('asphalt_02', 'concrete_pavement', 'plastered_wall_02')) {
    $metadata = Invoke-RestMethod -Uri "https://api.polyhaven.com/files/$asset"
    foreach ($channel in @(@('Diffuse', 'diff'), @('nor_gl', 'nor_gl'), @('Rough', 'rough'))) {
        $remote = $metadata.($channel[0]).'1k'.jpg
        if (-not $remote.url -or -not $remote.url.StartsWith('https://dl.polyhaven.org/file/ph-assets/Textures/')) {
            throw "Unexpected asset source: $asset"
        }
        $path = Join-Path $targetDirectory ($asset + '_' + $channel[1] + '_1k.jpg')
        if (-not (Test-Path -LiteralPath $path)) {
            Invoke-WebRequest -Uri $remote.url -OutFile $path
        }
        $digest = (Get-FileHash -LiteralPath $path -Algorithm MD5).Hash.ToLowerInvariant()
        if ($digest -ne $remote.md5) { throw "Checksum mismatch: $path" }
        [pscustomobject]@{ File = Split-Path -Leaf $path; Bytes = (Get-Item -LiteralPath $path).Length; SHA256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    }
}
