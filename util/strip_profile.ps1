<# example usage
.\strip_profile.ps1 `
    -InputFile "$env:USERPROFILE\.runelite\profiles2\`$rsprofile--1.properties" `
    -OutputFile ".\`$rsprofile--1.properties"
#>

 param (
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputFile
)

try {
    # Validate input file exists
    if (-not (Test-Path $InputFile)) {
        throw "Input file '$InputFile' does not exist."
    }

    # Define regex patterns for matching
    $patterns = @(
        '^rsprofile\.rsprofile\..*\.displayName',
        '^personalbest',
        '^rsprofile\.rsprofile\..*\.type'
    )

    # Read file and filter lines
    $filteredLines = Get-Content -Path $InputFile | Where-Object {
        foreach ($pattern in $patterns) {
            if ($_ -match $pattern) { return $true }
        }
        return $false
    }

    # Write filtered lines to output file
    $filteredLines | Set-Content -Path $OutputFile -Encoding UTF8

    Write-Host "Filtered lines saved to '$OutputFile'"
}
catch {
    Write-Error $_
}