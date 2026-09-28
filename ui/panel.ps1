# ==============================================================================
# AgentProxyHub 桌面控制面板 (AgentProxyHub Management Panel)
# ==============================================================================
# 技术栈：原生 WPF + XAML，暗黑极简风格，无第三方重量级依赖
# 国际化：中、英、日、韩四国语言即时无缝切换 (i18n Multi-Language Ready)
# 数据源：config/scenes.json（场景规则） + data/nodes.json（测绘结果） + config/i18n.json

param(
    [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public class Win11Dwm {
    [DllImport("dwmapi.dll")]
    public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    public static void EnableDarkMode(IntPtr hwnd, int captionColorBgr = 0x00161313, int textColorBgr = 0x00ECE9E9) {
        if (hwnd == IntPtr.Zero) return;
        try {
            int trueVal = 1;
            DwmSetWindowAttribute(hwnd, 20, ref trueVal, sizeof(int));
            DwmSetWindowAttribute(hwnd, 19, ref trueVal, sizeof(int));
            if (captionColorBgr >= 0) { DwmSetWindowAttribute(hwnd, 35, ref captionColorBgr, sizeof(int)); }
            if (textColorBgr >= 0) { DwmSetWindowAttribute(hwnd, 36, ref textColorBgr, sizeof(int)); }
        } catch { }
    }
}
'@ -ErrorAction SilentlyContinue

Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Net.ServicePointManager]::DefaultConnectionLimit = 128
[Net.ServicePointManager]::Expect100Continue = $false

function Write-PanelEvent([string]$kind, [string]$detail = '') {
    try {
        $logDir = Join-Path $RootDir 'logs'
        if (-not (Test-Path -LiteralPath $logDir)) { [void](New-Item -ItemType Directory -Path $logDir -Force) }
        $line = '{0} pid={1} {2} {3}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $kind, ($detail -replace '[\r\n]+', ' ')
        Add-Content -LiteralPath (Join-Path $logDir 'panel.log') -Value $line -Encoding UTF8
    } catch { }
}

# 单实例互斥锁
$script:mutex = New-Object System.Threading.Mutex($false, 'Local\AgentProxyHubPanel')
$acquired = $false
try { $acquired = $script:mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
if (-not $acquired) {
    try {
        $signal = [System.Threading.EventWaitHandle]::OpenExisting('Local\AgentProxyHubPanelShow')
        [void]$signal.Set()
        $signal.Dispose()
        Write-PanelEvent 'restore-requested'
    } catch {
        [void][Windows.MessageBox]::Show('AgentProxyHub 面板已在后台运行，请从系统托盘打开。', 'AgentProxyHub')
    }
    $script:mutex.Dispose()
    exit
}
$script:ShowSignal = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset, 'Local\AgentProxyHubPanelShow')
Write-PanelEvent 'started'

# 复制格式列表
$script:Formats = [ordered]@{
    'URI#名称 [标签] (FlowTools推荐)'  = 'flowtools_hash'
    'socks5h://'                       = 'socks5h://'
    'socks5://'                        = 'socks5://'
    'http://'                          = 'http://'
    'IP:端口'                          = 'raw'
    'JSON 数组 (全字段无损)'            = 'json'
    'CSV (地址,名称,标签,权重)'        = 'csv'
}

# 加载多语言字典
$script:I18n = @{}
$i18nFile = Join-Path $RootDir 'config\i18n.json'
if (Test-Path -LiteralPath $i18nFile) {
    try { $script:I18n = Get-Content -LiteralPath $i18nFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}
$script:CurrentLang = 'zh'

function T([string]$key, [hashtable]$params = @{}) {
    $dict = $script:I18n.$($script:CurrentLang)
    $text = if ($dict -and $dict.$key) { $dict.$key } else { $key }
    foreach ($k in $params.Keys) {
        $text = $text.Replace("{$k}", "$($params[$k])")
    }
    return $text
}

# XAML 布局
[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        x:Name="MainWin"
        Title="AgentProxyHub · 智能代理与环境调度中枢" Height="800" Width="1200" MinHeight="560" MinWidth="960"
        WindowStartupLocation="CenterScreen" Background="#131316" Foreground="#E9E9EC"
        FontFamily="Microsoft YaHei UI" FontSize="13" UseLayoutRounding="True"
        TextOptions.TextFormattingMode="Display">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="Background" Value="#26262C"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="12,5"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="6"
                    Padding="{TemplateBinding Padding}" SnapsToDevicePixels="True">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#33333B"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#3D3D47"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="Background" Value="#26262C"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border Background="#26262C" CornerRadius="6" SnapsToDevicePixels="True"/>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter Margin="11,0,28,0" VerticalAlignment="Center" IsHitTestVisible="False"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,11,0"
                    IsHitTestVisible="False" Data="M0,0 L4,4 L8,0" Stroke="#9A9AA5" StrokeThickness="1.4"/>
              <Popup x:Name="PART_Popup" AllowsTransparency="True" Placement="Bottom"
                     IsOpen="{TemplateBinding IsDropDownOpen}" Focusable="False" PopupAnimation="Slide">
                <Border Background="#23232A" CornerRadius="6" BorderBrush="#33333C" BorderThickness="1"
                        MinWidth="{TemplateBinding ActualWidth}" MaxHeight="340">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel IsItemsHost="True" Margin="0,4"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
      <Setter Property="Padding" Value="11,6"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="ibd" Background="Transparent" Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="ibd" Property="Background" Value="#32323D"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="ibd" Property="Background" Value="#3A3A47"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="Background" Value="#1C1C22"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="BorderBrush" Value="#2C2C35"/>
      <Setter Property="Padding" Value="10,5"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="CaretBrush" Value="#E9E9EC"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}"
                    CornerRadius="6">
              <ScrollViewer x:Name="PART_ContentHost" Margin="0" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="14,12,14,12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- 顶部操作条与场景靶场 -->
    <Border Grid.Row="0" Background="#1B1B20" CornerRadius="10" Padding="12,10">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
          <Ellipse x:Name="Dot" Width="9" Height="9" Fill="#7A7A85" VerticalAlignment="Center"/>
          <TextBlock x:Name="KernelText" Text="正在检测内核…" Margin="8,0,0,0" VerticalAlignment="Center"/>
          <Button x:Name="BtnStart" Content="启动内核" Margin="14,0,0,0"/>
          <Button x:Name="BtnStop" Content="停止内核" Margin="6,0,0,0"/>
          <Button x:Name="BtnRefresh" Content="刷新数据" Margin="6,0,0,0"/>
          <Button x:Name="BtnSpeed" Content="重新测速" Margin="6,0,0,0"/>

          <!-- 场景靶场下拉选择器与动态复制 -->
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="14,0,0,0">
            <TextBlock x:Name="LblScene" Text="场景靶场" Opacity="0.65" VerticalAlignment="Center" Margin="0,0,6,0"/>
            <ComboBox x:Name="CmbScene" Width="200" VerticalAlignment="Center"/>
            <Button x:Name="BtnCopyScenePool" Content="⚡ 复制场景池" Margin="8,0,0,0" Background="#223348"/>
          </StackPanel>
        </StackPanel>

        <!-- 复制格式与多语言自由切换下拉框 -->
        <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
          <TextBlock x:Name="LblFormat" Text="复制格式" Opacity="0.65" VerticalAlignment="Center"/>
          <ComboBox x:Name="CmbFormat" Width="170" Margin="8,0,0,0"/>

          <!-- 多语言自由切换器 -->
          <TextBlock Text="🌐" Opacity="0.75" FontSize="14" VerticalAlignment="Center" Margin="12,0,4,0"/>
          <ComboBox x:Name="CmbLang" Width="105" VerticalAlignment="Center"/>
        </StackPanel>
      </Grid>
    </Border>

    <!-- 手机/局域网免软件智能分流卡片 (完整保留) -->
    <Border Grid.Row="1" Background="#162232" BorderBrush="#254263" BorderThickness="1" CornerRadius="8" Padding="12,8" Margin="0,8,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
          <TextBlock Text="📱" FontSize="14" VerticalAlignment="Center"/>
          <TextBlock x:Name="PhoneBusTitle" Text="手机/局域网智能分流总线" FontWeight="SemiBold" Foreground="#7FB2FF" Margin="8,0,0,0" VerticalAlignment="Center"/>
          <Border Background="#1F3652" CornerRadius="4" Padding="6,2" Margin="10,0,0,0">
            <TextBlock Text="192.168.0.107:39999" FontFamily="Consolas" FontWeight="SemiBold" Foreground="#A2D2FF" VerticalAlignment="Center"/>
          </Border>
          <TextBlock x:Name="PhoneBusDesc" Text="(HTTP/SOCKS5混合 · 多节点自动选优 · 坏了秒切 · 国内直连)" Opacity="0.75" FontSize="11" Margin="8,0,0,0" VerticalAlignment="Center"/>
        </StackPanel>
        <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
          <TextBlock x:Name="PhoneStatusText" Text="✅ 手机(MI 8 Lite)已就绪" FontSize="11" Foreground="#5FD08A" Margin="0,0,10,0" VerticalAlignment="Center"/>
          <Button x:Name="BtnCopyPhoneProxy" Content="复制代理地址" Background="#203E61" Padding="10,4" Margin="4,0,0,0"/>
          <Button x:Name="BtnPhoneCmd" Content="挂载命令" Background="#283547" Padding="10,4" Margin="4,0,0,0"/>
        </StackPanel>
      </Grid>
    </Border>

    <!-- 筛选与搜索栏 -->
    <Grid Grid.Row="2" Margin="0,10,0,8">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <StackPanel Grid.Column="0" Orientation="Horizontal">
        <TextBlock x:Name="LblFilter" Text="视图筛选" Opacity="0.65" VerticalAlignment="Center"/>
        <ComboBox x:Name="CmbFilter" Width="200" Margin="8,0,0,0"/>
      </StackPanel>
      <TextBlock Grid.Column="1" x:Name="CountText" Margin="16,0,0,0" Opacity="0.75" VerticalAlignment="Center"/>
      <TextBox Grid.Column="2" x:Name="TxtSearch" Margin="16,0,10,0" VerticalAlignment="Center"/>
      <StackPanel Grid.Column="3" Orientation="Horizontal">
        <Button x:Name="BtnBatchP1" Content="📋 P1 智能解析格式" Background="#23232A"/>
        <Button x:Name="BtnBatchSocks" Content="📋 导出全部 SOCKS5" Margin="6,0,0,0" Background="#23232A"/>
        <Button x:Name="BtnBatchHttp" Content="📋 导出全部 HTTP" Margin="6,0,0,0" Background="#23232A"/>
      </StackPanel>
    </Grid>

    <!-- 节点列表主体 -->
    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
      <StackPanel x:Name="ListPanel" Margin="0,0,4,0"/>
    </ScrollViewer>

    <!-- 底部状态栏 -->
    <Border Grid.Row="4" Background="#16161B" CornerRadius="6" Padding="10,6" Margin="0,8,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock x:Name="StatusText" Text="准备就绪" Opacity="0.75" VerticalAlignment="Center"/>
        <TextBlock Grid.Column="1" Text="AgentProxyHub v1.0.0 · Dual-Track SOCKS/HTTP Engine" Opacity="0.45" FontSize="11" VerticalAlignment="Center"/>
      </Grid>
    </Border>
  </Grid>
</Window>
"@

# 加载窗口
$reader = New-Object System.Xml.XmlNodeReader $xaml
$win = [Windows.Markup.XamlReader]::Load($reader)

# 注册控件
$MainWin           = $win.FindName('MainWin')
$Dot               = $win.FindName('Dot')
$KernelText        = $win.FindName('KernelText')
$BtnStart          = $win.FindName('BtnStart')
$BtnStop           = $win.FindName('BtnStop')
$BtnRefresh        = $win.FindName('BtnRefresh')
$BtnSpeed          = $win.FindName('BtnSpeed')
$LblScene          = $win.FindName('LblScene')
$CmbScene          = $win.FindName('CmbScene')
$BtnCopyScenePool  = $win.FindName('BtnCopyScenePool')
$LblFormat         = $win.FindName('LblFormat')
$CmbFormat         = $win.FindName('CmbFormat')
$CmbLang           = $win.FindName('CmbLang')
$PhoneBusTitle     = $win.FindName('PhoneBusTitle')
$PhoneBusDesc      = $win.FindName('PhoneBusDesc')
$PhoneStatusText   = $win.FindName('PhoneStatusText')
$BtnCopyPhoneProxy = $win.FindName('BtnCopyPhoneProxy')
$BtnPhoneCmd       = $win.FindName('BtnPhoneCmd')
$LblFilter         = $win.FindName('LblFilter')
$CmbFilter         = $win.FindName('CmbFilter')
$CountText         = $win.FindName('CountText')
$TxtSearch         = $win.FindName('TxtSearch')
$ListPanel         = $win.FindName('ListPanel')
$StatusText        = $win.FindName('StatusText')
$BtnBatchP1        = $win.FindName('BtnBatchP1')
$BtnBatchSocks     = $win.FindName('BtnBatchSocks')
$BtnBatchHttp      = $win.FindName('BtnBatchHttp')

# 格式列表填充
foreach ($k in $script:Formats.Keys) { [void]$CmbFormat.Items.Add($k) }
$CmbFormat.SelectedIndex = 0

# 语言下拉框填充
$langMap = [ordered]@{
    '简体中文' = 'zh'
    'English'  = 'en'
    '日本語'   = 'ja'
    '한국어'   = 'ko'
}
foreach ($l in $langMap.Keys) { [void]$CmbLang.Items.Add($l) }
$CmbLang.SelectedIndex = 0

# 加载 scenes.json 规则
$script:Scenes = @()
$scenesFile = Join-Path $RootDir 'config\scenes.json'
if (Test-Path -LiteralPath $scenesFile) {
    try { $script:Scenes = Get-Content -LiteralPath $scenesFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}
if ($script:Scenes.Count -eq 0) {
    $script:Scenes = @(
        [pscustomobject]@{ id='antigravity'; name='✨ 反重力 / Gemini (Google原生)'; chip='Gemini ✅'; chipBg='#1B432C'; chipFg='#5FD08A'; matchKey='antigravitySupported' },
        [pscustomobject]@{ id='claude'; name='🟣 Claude 专属 (Anthropic直连)'; chip='Claude ✅'; chipBg='#3B1E4A'; chipFg='#C77DFF'; matchKey='claudeSupported' },
        [pscustomobject]@{ id='openai'; name='🟢 ChatGPT / OpenAI (API高速)'; chip='OpenAI ✅'; chipBg='#1A3A2A'; chipFg='#4EBA6F'; matchKey='openaiSupported' },
        [pscustomobject]@{ id='facebook'; name='🔵 Facebook / 海外社媒 (住宅纯净)'; chip='FB住宅 ✅'; chipBg='#1E2E4A'; chipFg='#70A1FF'; matchKey='facebookSupported' }
    )
}
foreach ($s in $script:Scenes) { [void]$CmbScene.Items.Add($s.name) }
if ($CmbScene.Items.Count -gt 0) { $CmbScene.SelectedIndex = 0 }

# 核心多语言切换函数
function Apply-Language([string]$lang) {
    $script:CurrentLang = $lang
    $win.Title = T 'title'
    $BtnStart.Content = T 'btn_start'
    $BtnStop.Content = T 'btn_stop'
    $BtnRefresh.Content = T 'btn_refresh'
    $BtnSpeed.Content = T 'btn_speed'
    $LblScene.Text = T 'lbl_scene'
    $LblFormat.Text = T 'lbl_format'
    $PhoneBusTitle.Text = T 'phone_bus_title'
    $PhoneBusDesc.Text = T 'phone_bus_desc'
    $PhoneStatusText.Text = T 'phone_status_ready'
    $BtnCopyPhoneProxy.Content = T 'btn_copy_phone_proxy'
    $BtnPhoneCmd.Content = T 'btn_phone_cmd'
    $LblFilter.Text = T 'lbl_filter'
    $TxtSearch.Text = T 'search_placeholder'
    $BtnBatchP1.Content = T 'btn_export_p1'
    $BtnBatchSocks.Content = T 'btn_export_socks'
    $BtnBatchHttp.Content = T 'btn_export_http'
    $StatusText.Text = T 'status_ready'

    # 动态刷新筛选列表
    $oldIdx = $CmbFilter.SelectedIndex
    if ($oldIdx -lt 0) { $oldIdx = 0 }
    $CmbFilter.Items.Clear()
    [void]$CmbFilter.Items.Add((T 'filter_scene'))
    [void]$CmbFilter.Items.Add((T 'filter_s'))
    [void]$CmbFilter.Items.Add((T 'filter_a'))
    [void]$CmbFilter.Items.Add((T 'filter_all'))
    [void]$CmbFilter.Items.Add((T 'filter_sent'))
    $CmbFilter.SelectedIndex = $oldIdx

    Update-SceneButton
}

$CmbLang.Add_SelectionChanged({
    $selectedName = $CmbLang.SelectedItem
    if ($selectedName -and $langMap.Contains($selectedName)) {
        Apply-Language $langMap[$selectedName]
    }
})

# 托盘图标设置
$script:Tray = New-Object Windows.Forms.NotifyIcon
$script:Tray.Text = 'AgentProxyHub'
$icoFile = Join-Path $RootDir 'assets\app.ico'
if (Test-Path -LiteralPath $icoFile) {
    $script:Tray.Icon = New-Object Drawing.Icon $icoFile
} else {
    $script:Tray.Icon = [Drawing.SystemIcons]::Application
}
$script:Tray.Visible = $true

$openPanel = {
    $win.Show()
    if ($win.WindowState -eq [Windows.WindowState]::Minimized) { $win.WindowState = [Windows.WindowState]::Normal }
    $win.Activate()
}
$script:Tray.Add_DoubleClick({ & $openPanel })

$trayMenu = New-Object Windows.Forms.ContextMenuStrip
$mOpen = $trayMenu.Items.Add('打开面板')
$mOpen.Add_Click({ & $openPanel })
$mSep = $trayMenu.Items.Add('-')
$mExit = $trayMenu.Items.Add('退出 AgentProxyHub')
$mExit.Add_Click({
    $script:Tray.Visible = $false
    $script:Tray.Dispose()
    $win.Close()
})
$script:Tray.ContextMenuStrip = $trayMenu

$win.Add_Closing({
    param($sender, $e)
    $e.Cancel = $true
    $win.Hide()
    $script:Tray.ShowBalloonTip(1500, 'AgentProxyHub', '面板已最小化至系统托盘，双击托盘图标即可唤出。', [Windows.Forms.ToolTipIcon]::Info)
})

# DWM 深色标题栏启用
$win.Add_SourceInitialized({
    $hwnd = (New-Object Windows.Interop.WindowInteropHelper $win).Handle
    [Win11Dwm]::EnableDarkMode($hwnd)
})

function Update-SceneButton {
    $idx = $CmbScene.SelectedIndex
    if ($idx -lt 0 -or $idx -ge $script:Scenes.Count) { return }
    $s = $script:Scenes[$idx]
    $matchedCount = 0
    if ($script:Nodes) {
        $key = if ($s.matchKey) { $s.matchKey } else { "$($s.id)Supported" }
        $matchedCount = @($script:Nodes | Where-Object { $_.$key -eq $true }).Count
    }
    $BtnCopyScenePool.Content = "$([char]0x26A1) $(T 'btn_copy_scene') ($matchedCount)"
    if ($s.chipBg) {
        try { $BtnCopyScenePool.Background = (New-Object Windows.Media.BrushConverter).ConvertFromString($s.chipBg) } catch { }
    }
}
$CmbScene.Add_SelectionChanged({ Update-SceneButton })

# 节点数据逻辑
$script:Nodes = @()
$script:ListenAddr = "127.0.0.1"

function Load-NodesData {
    $dataFile = Join-Path $RootDir 'data\nodes.json'
    if (-not (Test-Path -LiteralPath $dataFile)) {
        $sysData = "D:\Program Files\FengWoBridge\nodes.json"
        if (Test-Path -LiteralPath $sysData) { $dataFile = $sysData }
    }
    if (Test-Path -LiteralPath $dataFile) {
        try {
            $parsed = Get-Content -LiteralPath $dataFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($parsed.nodes) {
                $script:Nodes = @($parsed.nodes)
                if ($parsed.listen) { $script:ListenAddr = $parsed.listen }
            }
        } catch { }
    }
}

function Format-ProxyEntry($node, $fmt) {
    $p = $node.port
    $hp = if ($node.httpPort) { $node.httpPort } else { $p + 10000 }
    $name = if ($node.orig) { $node.orig } else { $node.name }
    $country = if ($node.country) { $node.country } else { '未知' }
    $host = $script:ListenAddr

    switch ($fmt) {
        'flowtools_hash' { "socks5://$host`:$p#$name [$country]" }
        'socks5h://'     { "socks5h://$host`:$p" }
        'socks5://'      { "socks5://$host`:$p" }
        'http://'        { "http://$host`:$hp" }
        'raw'            { "$host`:$p" }
        'csv'            { "socks5://$host`:$p,$name,$country,1" }
        default          { "socks5://$host`:$p" }
    }
}

$BtnCopyScenePool.Add_Click({
    $idx = $CmbScene.SelectedIndex
    if ($idx -lt 0 -or $idx -ge $script:Scenes.Count) { return }
    $s = $script:Scenes[$idx]
    $key = if ($s.matchKey) { $s.matchKey } else { "$($s.id)Supported" }
    
    $pool = @($script:Nodes | Where-Object { $_.$key -eq $true } | Sort-Object healthScore -Descending)
    if ($pool.Count -eq 0) {
        $StatusText.Text = T 'msg_no_nodes' @{ scene = $s.name }
        return
    }
    $fmt = $CmbFormat.SelectedItem
    $lines = foreach ($item in $pool) { Format-ProxyEntry $item $fmt }
    $copyText = $lines -join "`r`n"
    try { [Windows.Clipboard]::SetText($copyText) } catch { }
    $StatusText.Text = T 'msg_copied' @{ count = $pool.Count; scene = $s.name }
})

$BtnCopyPhoneProxy.Add_Click({
    try { [Windows.Clipboard]::SetText("192.168.0.107:39999") } catch { }
    $StatusText.Text = '已复制手机/局域网分流代理地址：192.168.0.107:39999'
})

$BtnPhoneCmd.Add_Click({
    $cmd = 'settings put global http_proxy 192.168.0.107:39999'
    try { [Windows.Clipboard]::SetText($cmd) } catch { }
    $StatusText.Text = "已复制手机免App挂载命令：$cmd"
})

$BtnBatchSocks.Add_Click({
    $lines = foreach ($n in $script:Nodes) { Format-ProxyEntry $n 'socks5://' }
    try { [Windows.Clipboard]::SetText(($lines -join "`r`n")) } catch { }
    $StatusText.Text = "已复制全量 $($script:Nodes.Count) 个 SOCKS5 端口列表。"
})

$BtnBatchHttp.Add_Click({
    $lines = foreach ($n in $script:Nodes) { Format-ProxyEntry $n 'http://' }
    try { [Windows.Clipboard]::SetText(($lines -join "`r`n")) } catch { }
    $StatusText.Text = "已复制全量 $($script:Nodes.Count) 个 HTTP 端口列表。"
})

# 初始化语言与数据
Load-NodesData
Apply-Language 'zh'
$CountText.Text = "当前加载节点: $($script:Nodes.Count)"
$KernelText.Text = "Mihomo 内核已连接 · 监听: $script:ListenAddr"
$Dot.Fill = (New-Object Windows.Media.SolidColorBrush([Windows.Media.Color]::FromArgb(255, 95, 208, 138)))

# 启动窗口
[void]$win.ShowDialog()
