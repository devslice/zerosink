$file = "static/index.html"
$content = Get-Content $file -Raw

Write-Output "=== Step 1: Replace icon names globally ==="

$mapping = @{
    'fa-chart-bar' = 'lni-bar-chart-4'
    'fa-file-lines' = 'lni-file-multiple'
    'fa-circle-question' = 'lni-question-mark-circle'
    'fa-sitemap' = 'lni-hierarchy-1'
    'fa-gear' = 'lni-gear-1'
    'fa-user' = 'lni-user-4'
    'fa-lock' = 'lni-locked-1'
    'fa-key' = 'lni-key-1'
    'fa-circle-check' = 'lni-check-circle-1'
    'fa-circle-exclamation' = 'lni-ban-2'
    'fa-circle-xmark' = 'lni-xmark-circle'
    'fa-circle-info' = 'lni-info'
    'fa-circle-pause' = 'lni-pause'
    'fa-circle-notch' = 'lni-spinner-3'
    'fa-check' = 'lni-check'
    'fa-check-double' = 'lni-check'
    'fa-xmark' = 'lni-xmark'
    'fa-plus' = 'lni-plus'
    'fa-minus' = 'lni-minus'
    'fa-arrows-rotate' = 'lni-refresh-circle-1-clockwise'
    'fa-trash' = 'lni-trash-3'
    'fa-trash-can' = 'lni-trash-3'
    'fa-arrow-right' = 'lni-arrow-right'
    'fa-arrow-left' = 'lni-arrow-left'
    'fa-arrow-right-from-bracket' = 'lni-exit'
    'fa-circle-arrow-up' = 'lni-arrow-upward'
    'fa-clock' = 'lni-stopwatch'
    'fa-clock-rotate-left' = 'lni-refresh-circle-1-clockwise'
    'fa-cloud-arrow-down' = 'lni-cloud-download'
    'fa-download' = 'lni-download-1'
    'fa-upload' = 'lni-cloud-upload'
    'fa-bolt' = 'lni-bolt-2'
    'fa-server' = 'lni-database-2'
    'fa-globe' = 'lni-globe-1'
    'fa-code' = 'lni-code-1'
    'fa-bell' = 'lni-bell-1'
    'fa-info' = 'lni-info'
    'fa-flag' = 'lni-flag-1'
    'fa-crown' = 'lni-crown-3'
    'fa-compass' = 'lni-compass-drafting-2'
    'fa-briefcase' = 'lni-briefcase-1'
    'fa-clipboard' = 'lni-clipboard'
    'fa-ban' = 'lni-ban-2'
    'fa-bars' = 'lni-menu-hamburger-1'
    'fa-laptop' = 'lni-laptop-2'
    'fa-mobile-screen-button' = 'lni-telephone-1'
    'fa-gamepad' = 'lni-game-pad-modern-1'
    'fa-film' = 'lni-camera-movie-1'
    'fa-network-wired' = 'lni-vector-nodes-6'
    'fa-users' = 'lni-user-multiple-4'
    'fa-user-shield' = 'lni-shield-2-check'
    'fa-list-ul' = 'lni-agenda'
    'fa-arrow-trend-up' = 'lni-trend-up-1'
    'fa-shield-halved' = 'lni-shield-2'
    'fa-map-location-dot' = 'lni-map-pin-5'
    'fa-triangle-exclamation' = 'lni-ban-2'
    'fa-wifi' = 'lni-tower-broadcast-1'
    'fa-desktop' = 'lni-monitor'
    'fa-list-check' = 'lni-check-circle-1'
    'fa-floppy-disk' = 'lni-floppy-disk-1'
    'fa-rotate' = 'lni-refresh-circle-1-clockwise'
    'fa-sync' = 'lni-refresh-circle-1-clockwise'
    'fa-spinner' = 'lni-spinner-3'
    'fa-sun' = 'lni-sun-1'
    'fa-moon' = 'lni-moon-half-right-5'
    'fa-file-invoice' = 'lni-file-pencil'
    'fa-gears' = 'lni-gears-3'
    'fa-database' = 'lni-database-2'
}

# Sort keys by length descending to avoid substring collisions (e.g. fa-gear before fa-gears)
$sortedKeys = $mapping.Keys | Sort-Object Length -Descending
foreach ($fa in $sortedKeys) {
    $lni = $mapping[$fa]
    $content = $content -replace [regex]::Escape($fa), $lni
}

Write-Output "Step 2: Protect password toggle lines from fa-solid replacement"

# Protect class="fa-solid" when followed by :class containing fa-eye or fa-eye-slash
$content = $content -replace '(class=")fa-solid(" :class="[^"]*?fa-eye[^"]*?")', '${1}PW_KEEP_FA_SOLID$2'

Write-Output "Step 3: Replace fa-solid/fa-regular/fa-brands with lni globally"

$content = $content -replace '\bfa-solid\b', 'lni'
$content = $content -replace '\bfa-regular\b', 'lni'
$content = $content -replace '\bfa-brands\b', 'lni'

Write-Output "Step 4: Replace fa-spin with lni-is-spinning"

$content = $content -replace '\bfa-spin\b', 'lni-is-spinning'

Write-Output "Step 5: Restore logo shield instances"

# Login & setup page logos
$content = $content -replace 'lni lni-shield-2 text-brandgreen text-4xl', 'fa-solid fa-shield-halved text-brandgreen text-4xl'
# Mobile sidebar logo
$content = $content -replace 'lni lni-shield-2 text-brandgreen text-lg', 'fa-solid fa-shield-halved text-brandgreen text-lg'
# Desktop sidebar logo
$content = $content -replace 'lni lni-shield-2 text-brandgreen text-2xl', 'fa-solid fa-shield-halved text-brandgreen text-2xl'
# Mobile header logo (wrapped in text-lime-600 span)
$content = $content -replace '<span class="text-lime-600 dark:text-lime-400"><i class="lni lni-shield-2"></i></span>', '<span class="text-lime-600 dark:text-lime-400"><i class="fa-solid fa-shield-halved"></i></span>'

Write-Output "Step 6: Restore password toggle lines"

$content = $content -replace 'PW_KEEP_FA_SOLID', 'fa-solid'

Write-Output "Step 7: Restore kept FA icons (no LNI equivalent)"

# microchip, qrcode
$content = $content -replace 'lni fa-microchip', 'fa-solid fa-microchip'
$content = $content -replace 'lni fa-qrcode', 'fa-solid fa-qrcode'

Write-Output "Step 8: Clean up double spaces"

while ($content.IndexOf('  ') -ge 0) {
    $content = $content -replace '  ', ' '
}

Write-Output "Writing file..."

Set-Content -Path $file -Value $content -NoNewline

Write-Output "Done!"
