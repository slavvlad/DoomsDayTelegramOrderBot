# get current folder location
$currentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$exeName = "DoomsDayTelegramOrderBot.exe"
$exePath = Join-Path $currentDirectory $exeName

Write-Output "Current folder path: $exePath"

# Service properties
$serviceName = "DoomsdayBot"
$displayName = "DoomsdayBot"
$description = "This is a custom service that runs an exe file."

# Create Service
sc.exe create $serviceName binPath= `"$exePath`" start= auto
sc.exe description $serviceName $description
sc.exe config $serviceName DisplayName= $displayName

# Start Service
Start-Service $serviceName