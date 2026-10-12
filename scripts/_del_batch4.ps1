$trace = "$env:TEMP\del_trace.txt"
function Log($m) { Add-Content -Path $script:trace -Value $m -Encoding UTF8 }
"=== start ===" | Set-Content -Path $trace -Encoding UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if (-not ("MUM" -as [type])) {
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class MUM {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public static void Max(IntPtr h){ ShowWindow(h, 3); System.Threading.Thread.Sleep(400); SetForegroundWindow(h); System.Threading.Thread.Sleep(400); }
  public static void Move(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(160); }
  public static void RClick(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(260); mouse_event(0x0008,0,0,0,IntPtr.Zero); mouse_event(0x0010,0,0,0,IntPtr.Zero); }
  public static void Click(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(260); mouse_event(0x0002,0,0,0,IntPtr.Zero); mouse_event(0x0004,0,0,0,IntPtr.Zero); }
}
"@
}
function NumV($v) { try { $d = [double]$v; if ([double]::IsNaN($d) -or [double]::IsInfinity($d)) { return -9999 }; return [int]$d } catch { return -9999 } }
function RectOf($e) { $r = $e.Current.BoundingRectangle; return ("[" + (NumV $r.X) + "," + (NumV $r.Y) + "," + (NumV $r.Width) + "," + (NumV $r.Height) + "]") }
function Get-Seewo() {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $lbCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, "CoursewareListBox")
    foreach ($p in (Get-Process -Name EasiNote -ErrorAction SilentlyContinue)) {
        $pc = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
        $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pc)
        for ($i = 0; $i -lt $wins.Count; $i++) {
            $cand = $wins.Item($i)
            $cl = $cand.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $lbCond)
            if ($null -ne $cl) { return @{ W = $cand; LB = $cl } }
        }
    }
    return $null
}
function FindId($win, $id) {
    $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
}
$cfg = Get-Content -Raw -Encoding UTF8 (Join-Path $env:TEMP "del_targets.json") | ConvertFrom-Json
$exact = @($cfg.exact | Where-Object { $_ })
$contains = @($cfg.contains | Where-Object { $_ })
$prefix = [string]$cfg.rowPrefix
$guard = [string]$cfg.dialogGuard
Log ("cfg exact=" + $exact.Count + " contains=" + $contains.Count + " prefix='" + $prefix + "' guard='" + $guard + "'")

$deleted = 0
$s = Get-Seewo
if ($null -eq $s) { Log "ABORT: no seewo window" } else {
    [MUM]::Max([IntPtr]$s.W.Current.NativeWindowHandle)
    Start-Sleep -Milliseconds 900
    $s = Get-Seewo
    $pb = FindId $s.W "PART_PrimaryButton"
    if ($null -ne $pb) {
        $r = $pb.Current.BoundingRectangle
        Log "dismiss pending dialog"
        [MUM]::Click((NumV $r.X) + [int]((NumV $r.Width)/2), (NumV $r.Y) + [int]((NumV $r.Height)/2))
        Start-Sleep -Milliseconds 2200
    }
    # ---------- refresh the list first ----------
    # The list keeps a CACHED snapshot; without refreshing, FindItemByProperty cannot
    # see rows that were created a moment ago (returns null -> silent 0 deletions).
    $rc = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, "RefreshButton")
    $rb = $s.W.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $rc)
    if ($null -ne $rb) {
        $rr = $rb.Current.BoundingRectangle
        [MUM]::Click((NumV $rr.X) + [int]((NumV $rr.Width)/2), (NumV $rr.Y) + [int]((NumV $rr.Height)/2))
        Log "clicked RefreshButton"
        Start-Sleep -Milliseconds 5000
        $s = Get-Seewo
    } else { Log "WARN no RefreshButton" }

    # ---------- generic: delete one item ----------
    function DeleteItem($el, $label) {
        $r = $el.Current.BoundingRectangle
        $x = NumV $r.X; $y = NumV $r.Y; $h = NumV $r.Height
        if ($y -lt 5 -or $y -gt 1015) { Log ("SKIP offscreen " + $label + " " + (RectOf $el)); return $false }
        $cx = $x + 400; $cy = $y + [int]($h / 2)
        $menu = $null
        for ($try = 1; $try -le 3; $try++) {
            [MUM]::Move(960, 1000); Start-Sleep -Milliseconds 200
            [MUM]::RClick($cx, $cy)
            Start-Sleep -Milliseconds 1400
            $sw = Get-Seewo
            $menu = FindId $sw.W "DeleteMenuItem"
            if ($null -ne $menu) { break }
            Log ("  rclick retry " + $try + " for " + $label)
        }
        if ($null -eq $menu) { Log ("FAIL no menu for " + $label); return $false }
        $dr = $menu.Current.BoundingRectangle
        $dx = (NumV $dr.X) + [int]((NumV $dr.Width)/2)
        $dy = (NumV $dr.Y) + [int]((NumV $dr.Height)/2)
        [MUM]::Move($dx, $dy); Start-Sleep -Milliseconds 250
        [MUM]::Click($dx, $dy)
        Start-Sleep -Milliseconds 1600
        $sw = Get-Seewo
        $txtCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Text)
        $ts = $sw.W.FindAll([System.Windows.Automation.TreeScope]::Descendants, $txtCond)
        $hasGuard = $false
        for ($i = 0; $i -lt $ts.Count; $i++) { $n = $ts.Item($i).Current.Name; if ($n -and $n.Contains($guard)) { $hasGuard = $true } }
        $pb2 = FindId $sw.W "PART_PrimaryButton"
        if ($null -eq $pb2 -or -not $hasGuard) { Log ("FAIL confirm guard for " + $label + " btn=" + ($null -ne $pb2) + " guard=" + $hasGuard); return $false }
        $pr = $pb2.Current.BoundingRectangle
        [MUM]::Click((NumV $pr.X) + [int]((NumV $pr.Width)/2), (NumV $pr.Y) + [int]((NumV $pr.Height)/2))
        Start-Sleep -Milliseconds 1900
        Log ("DELETED " + $label)
        return $true
    }
    # ---------- phase 1: name CONTAINS keyword (loop over visible rows) ----------
    for ($round = 0; $round -lt 25; $round++) {
        $s = Get-Seewo
        if ($null -eq $s) { Log "seewo gone"; break }
        $items = $s.LB.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
        $target = $null; $tname = ""
        for ($i = 0; $i -lt $items.Count; $i++) {
            $nm = $items.Item($i).Current.Name
            $n2 = $nm -replace '\[..\]', ''
            foreach ($c in $contains) { if ($n2 -like ('*' + $c + '*')) { $target = $items.Item($i); $tname = $nm } }
            if ($null -ne $target) { break }
        }
        if ($null -eq $target) { Log ("phase1 done at round " + $round); break }
        Log ("phase1 round " + $round + " -> '" + $tname + "' " + (RectOf $target))
        $ok = DeleteItem $target $tname
        if ($ok) { $deleted++ } else { Log "phase1 stop"; break }
    }
    # ---------- phase 2: EXACT name (ItemContainerPattern for virtualized rows) ----------
    foreach ($n in $exact) {
        $full = $prefix + $n
        for ($k = 0; $k -lt 6; $k++) {
            $s = Get-Seewo
            if ($null -eq $s) { Log "seewo gone"; break }
            $icp = $null
            try { $icp = $s.LB.GetCurrentPattern([System.Windows.Automation.ItemContainerPattern]::Pattern) } catch { }
            if ($null -eq $icp) { Log "no ItemContainerPattern"; break }
            $found = $null
            # With duplicate names, the list virtualization cache lags after a delete and
            # FindItemByProperty briefly returns null; retry a few times before giving up.
            # NOTE: keep this file ASCII-only - non-ASCII comments break .ps1 parsing.
            for ($r = 0; $r -lt 5; $r++) {
                try { $found = $icp.FindItemByProperty($null, [System.Windows.Automation.AutomationElement]::NameProperty, $full) } catch { Log ("FindItemByProperty err: " + $_.Exception.Message) }
                if ($null -ne $found) { break }
                Start-Sleep -Milliseconds 2600
                $s = Get-Seewo
                if ($null -eq $s) { break }
                try { $icp = $s.LB.GetCurrentPattern([System.Windows.Automation.ItemContainerPattern]::Pattern) } catch { break }
            }
            if ($null -eq $found) { Log ("phase2 '" + $full + "' not found (k=" + $k + ")"); break }
            try { $found.GetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern).ScrollIntoView() } catch { }
            Start-Sleep -Milliseconds 500
            $s2 = Get-Seewo
            $icp2 = $s2.LB.GetCurrentPattern([System.Windows.Automation.ItemContainerPattern]::Pattern)
            $found2 = $icp2.FindItemByProperty($null, [System.Windows.Automation.AutomationElement]::NameProperty, $full)
            if ($null -eq $found2) { Log ("phase2 '" + $full + "' lost after scroll"); break }
            Log ("phase2 '" + $full + "' k=" + $k + " " + (RectOf $found2))
            $ok = DeleteItem $found2 $full
            if ($ok) { $deleted++ } else { Log "phase2 stop"; break }
        }
    }
}
Log ("TOTAL deleted = " + $deleted)
"done"
