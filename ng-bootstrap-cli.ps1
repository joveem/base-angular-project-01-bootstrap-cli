Param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)
python "$PSScriptRoot\project_bootstrap.py" @Args
