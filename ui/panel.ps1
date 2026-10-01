# AgentProxyHub —— 取用代理配置的控制面板（WPF 原生窗口，无浏览器、无本地服务）
# 数据来源：nodes.json（由 gen-report.ps1 生成）+ 内核控制 API（延迟测速）
# 特性：按地区折叠分组、一环境一端口随取随用、蜂窝订阅刷新后自动同步、诚实标注未探测项

param(
    [string]$Dir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [ValidateSet('Export', 'Guard')]
    [string]$View = 'Export'
)

$ErrorActionPreference = 'Stop'

# ---- AgentProxyHub 运行布局 ----
# 数据/配置分目录存放；找不到回退根目录，两边都能跑
function Get-RunFile([string]$name) {
    foreach ($sub in @('data', 'config', '')) {
        $p = if ($sub) { Join-Path $Dir "$sub\$name" } else { Join-Path $Dir $name }
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return (Join-Path $Dir $name)
}
function Get-CoreFile([string]$name) {
    $p = Join-Path $Dir "core\$name"
    if (Test-Path -LiteralPath $p) { return $p }
    return (Join-Path $Dir $name)
}
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
            // DWMWA_USE_IMMERSIVE_DARK_MODE (20 for Win11/Win10 20H1+, 19 for older Win10)
            DwmSetWindowAttribute(hwnd, 20, ref trueVal, sizeof(int));
            DwmSetWindowAttribute(hwnd, 19, ref trueVal, sizeof(int));
            if (captionColorBgr >= 0) {
                // DWMWA_CAPTION_COLOR (35)
                DwmSetWindowAttribute(hwnd, 35, ref captionColorBgr, sizeof(int));
            }
            if (textColorBgr >= 0) {
                // DWMWA_TEXT_COLOR (36)
                DwmSetWindowAttribute(hwnd, 36, ref textColorBgr, sizeof(int));
            }
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
        $logDir = Join-Path $Dir 'logs'
        if (-not (Test-Path -LiteralPath $logDir)) { [void](New-Item -ItemType Directory -Path $logDir -Force) }
        $line = '{0} pid={1} {2} {3}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $kind, ($detail -replace '[\r\n]+', ' ')
        Add-Content -LiteralPath (Join-Path $logDir 'panel.log') -Value $line -Encoding UTF8
    } catch { }
}

# 单实例
$script:mutex = New-Object System.Threading.Mutex($false, 'Local\AgentProxyHubPanel')
$acquired = $false
try { $acquired = $script:mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
if (-not $acquired) {
    try {
        $signal = [System.Threading.EventWaitHandle]::OpenExisting('Local\AgentProxyHubPanelShow')
        [void]$signal.Set()
        $signal.Dispose()
        if ($View -eq 'Guard') {
            try {
                $gsig = [System.Threading.EventWaitHandle]::OpenExisting('Local\AgentProxyHubPanelGuard')
                [void]$gsig.Set()
                $gsig.Dispose()
            } catch { }
        }
        Write-PanelEvent 'restore-requested'
    } catch {
        Write-PanelEvent 'restore-request-failed' $_.Exception.Message
        [void][Windows.MessageBox]::Show('面板已在运行，请从系统托盘打开。', 'AgentProxyHub')
    }
    $script:mutex.Dispose()
    exit
}
$script:ShowSignal = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset, 'Local\AgentProxyHubPanelShow')
$script:GuardSignal = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset, 'Local\AgentProxyHubPanelGuard')
# 命名事件若是复用的既有对象，initialState 会被忽略；这里显式复位，避免上一次残留的信号误触发换视图
$script:ShowSignal.Reset()
$script:GuardSignal.Reset()
Write-PanelEvent 'started'

# ---------------- 国家/地区中文名 ----------------
$script:RegionCn = @{
    AR='阿根廷'; AU='澳大利亚'; AT='奥地利'; AZ='阿塞拜疆'; BH='巴林'; BD='孟加拉'; BR='巴西'
    BG='保加利亚'; CA='加拿大'; CL='智利'; CO='哥伦比亚'; CZ='捷克'; DK='丹麦'; EC='厄瓜多尔'
    EG='埃及'; FR='法国'; DE='德国'; GR='希腊'; HK='香港'; HU='匈牙利'; IS='冰岛'; IN='印度'
    ID='印尼'; IQ='伊拉克'; IL='以色列'; JP='日本'; KZ='哈萨克斯坦'; KG='吉尔吉斯斯坦'
    LT='立陶宛'; MO='澳门'; MY='马来西亚'; MX='墨西哥'; MA='摩洛哥'; NP='尼泊尔'; NG='尼日利亚'
    MK='北马其顿'; OM='阿曼'; PK='巴基斯坦'; PE='秘鲁'; PH='菲律宾'; PL='波兰'; PT='葡萄牙'
    RU='俄罗斯'; SA='沙特阿拉伯'; SG='新加坡'; SI='斯洛文尼亚'; ZA='南非'; KR='韩国'; ES='西班牙'
    SE='瑞典'; CH='瑞士'; TW='台湾'; TH='泰国'; NL='荷兰'; TG='多哥'; TR='土耳其'; UA='乌克兰'
    AE='阿联酋'; GB='英国'; US='美国'; VN='越南'
}

$script:Formats = [ordered]@{
    'URI#名称 [标签] (FlowTools推荐)'  = 'flowtools_hash'
    'socks5h://'                       = 'socks5h://'
    'socks5://'                        = 'socks5://'
    'http://'                          = 'http://'
    'IP:端口'                          = 'raw'
    'URI#名称|标签|权重'                = 'flowtools_pipe'
    'JSON 数组 (全字段无损)'            = 'json'
    'CSV (地址,名称,标签,权重)'        = 'csv'
}

function Get-NodeCleanName($node) {
    if (-not $node) { return "未知节点" }
    $cnMap = @{
        'United States'='美国'; 'United Kingdom'='英国'; 'Germany'='德国';
        'France'='法国'; 'Japan'='日本'; 'Canada'='加拿大'; 'Switzerland'='瑞士';
        'Spain'='西班牙'; 'Italy'='意大利'; 'Australia'='澳大利亚';
        'Taiwan'='台湾'; 'Mexico'='墨西哥'; 'Russia'='俄罗斯'; 'Hong Kong'='香港';
        'China'='中国'; 'Singapore'='新加坡'; 'South Korea'='韩国'
    }
    $c = if ($node.googleCountry -and $cnMap.ContainsKey($node.googleCountry)) { $cnMap[$node.googleCountry] }
         elseif ($node.country -and $cnMap.ContainsKey($node.country)) { $cnMap[$node.country] }
         elseif ($node.country) { $node.country } else { '节点' }
    $orig = if ($node.orig) { $node.orig } else { '' }
    $kind = if ($orig -like '*家宽*' -or $orig -like '*住宅*' -or $node.kind -like '*家宽*') { '家宽' }
            elseif ($orig -like '*高速*') { '高速' }
            elseif ($orig -like '*IEPL*') { 'IEPL专线' }
            elseif ($orig -like '*专线*' -or $node.kind -like '*专线*') { '专线' }
            elseif ($orig -like '*原生*') { '原生' }
            else { '专线' }
    $air = if ($node.airport) { $node.airport } elseif ($node.port -ge 22001) { '星辰' } else { '蜂窝' }
    return "$air-$c-$kind$($node.port)"
}

function Format-ProxyEntry($node, $fmt) {
    $listen = $script:ListenAddr
    $port = $node.port
    $httpPort = if ($node.httpPort) { $node.httpPort } else { $port + 10000 }
    $name = Get-NodeCleanName $node
    $tag = if ($node.antigravitySupported) { "gemini-pure" } else { "general" }
    $weight = 1
    
    switch ($fmt) {
        'socks5h://'      { "socks5h://${listen}:${port}" }
        'socks5://'       { "socks5://${listen}:${port}" }
        'http://'         { "http://${listen}:${httpPort}" }
        'IP:端口'         { "${listen}:${port}" }
        'URI#名称 [标签] (FlowTools推荐)' {
            "socks5h://${listen}:${port}#$name [$tag]"
        }
        'URI#名称|标签|权重' {
            "socks5h://${listen}:${port}#$name|$tag|$weight"
        }
        'CSV (地址,名称,标签,权重)' {
            "socks5h://${listen}:${port},$name,$tag,$weight"
        }
        'JSON 数组 (全字段无损)' {
            @{
                url = "socks5h://${listen}:${port}"
                name = $name
                tags = @($tag)
                priority = $weight
                is_healthy = $true
                country = $node.country
                googleCountry = $node.googleCountry
                port = $port
            } | ConvertTo-Json -Compress
        }
        default {
            if ($script:Formats[$fmt] -and $script:Formats[$fmt] -ne 'raw') {
                "$($script:Formats[$fmt])${listen}:${port}"
            } else {
                "${listen}:${port}"
            }
        }
    }
}
# 这些格式走 HTTP 端口（310xx），其余走 SOCKS 端口（210xx）
$script:HttpFormats = @('http://')

# ---------------- 界面 ----------------
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="AgentProxyHub · 极简驾驶舱" Height="780" Width="1240" MinHeight="540" MinWidth="900"
        WindowStartupLocation="CenterScreen" Background="#090B10" Foreground="#F1F4F2"
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
                <Setter TargetName="ibd" Property="Background" Value="#31313A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="Background" Value="#1E1E23"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="CaretBrush" Value="#7FB2FF"/>
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
    </Style>
    <Style TargetType="Expander">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
      <Setter Property="Margin" Value="0,0,0,6"/>
    </Style>
    <Style TargetType="TextBlock">
      <Setter Property="FontFamily" Value="Microsoft YaHei UI"/>
    </Style>
    <!-- Dark Minimal ScrollBar -->
    <Style TargetType="{x:Type ScrollBar}">
      <Setter Property="Stylus.IsPressAndHoldEnabled" Value="false"/>
      <Setter Property="Stylus.IsFlicksEnabled" Value="false"/>
      <Setter Property="Width" Value="7"/>
      <Setter Property="MinWidth" Value="7"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="{x:Type ScrollBar}">
            <Grid x:Name="Bg" SnapsToDevicePixels="true" Background="Transparent">
              <Track x:Name="PART_Track" IsDirectionReversed="true">
                <Track.Thumb>
                  <Thumb x:Name="Thumb">
                    <Thumb.Template>
                      <ControlTemplate TargetType="{x:Type Thumb}">
                        <Border x:Name="ThumbBorder" Background="#3A3A44" CornerRadius="3.5" Margin="1,2,1,2"/>
                        <ControlTemplate.Triggers>
                          <Trigger Property="IsMouseOver" Value="true">
                            <Setter TargetName="ThumbBorder" Property="Background" Value="#555566"/>
                          </Trigger>
                          <Trigger Property="IsDragging" Value="true">
                            <Setter TargetName="ThumbBorder" Property="Background" Value="#707084"/>
                          </Trigger>
                        </ControlTemplate.Triggers>
                      </ControlTemplate>
                    </Thumb.Template>
                  </Thumb>
                </Track.Thumb>
              </Track>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <!-- 巡检风控视图用的深色表格控件 -->
    <Style TargetType="ListView">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
    </Style>
    <Style TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#E9E9EC"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="gib" Background="Transparent" CornerRadius="5" Padding="{TemplateBinding Padding}">
              <GridViewRowPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="gib" Property="Background" Value="#22222A"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="gib" Property="Background" Value="#2A3550"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="GridViewColumnHeader">
      <Setter Property="Background" Value="#232329"/>
      <Setter Property="Foreground" Value="#A9A9B6"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="GridViewColumnHeader">
            <Border Background="{TemplateBinding Background}" CornerRadius="5" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Left" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ProgressBar">
      <Setter Property="Height" Value="4"/>
      <Setter Property="Foreground" Value="#B7FF00"/>
      <Setter Property="Background" Value="#1B2028"/>
      <Setter Property="BorderThickness" Value="0"/>
    </Style>
  </Window.Resources>
  <Grid Margin="24">
    <Grid x:Name="ViewCockpit">
      <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
      <Border Background="#130D17" BorderBrush="#B63A2E" BorderThickness="1" Padding="18" CornerRadius="2">
        <Grid>
          <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
          <StackPanel>
            <TextBlock Text="APH // GATEWAY OBSERVATORY" Foreground="#FF6B35" FontFamily="Consolas" FontSize="13" FontWeight="Bold"/>
            <TextBlock Text="常态化网关情报 · 人类可读层" Foreground="#D8A28E" FontFamily="Consolas" FontSize="11" Margin="0,5,0,0"/>
            <TextBlock x:Name="CockpitState" Text="状态未知" FontSize="30" FontWeight="SemiBold" Margin="0,11,0,3"/>
            <TextBlock x:Name="CockpitDetail" Text="检测本项目内核 · 不改变账号绑定" Foreground="#B9AFCA" TextWrapping="Wrap"/>
          </StackPanel>
          <StackPanel Grid.Column="1" Margin="22,0,24,0" VerticalAlignment="Center">
            <TextBlock Text="SYSTEM CLOCK" Foreground="#8F7772" FontFamily="Consolas" FontSize="10"/>
            <TextBlock x:Name="CockpitClock" Text="--:--:--" Foreground="#FFB347" FontFamily="Consolas" FontSize="24"/>
            <TextBlock x:Name="FeedModeText" Text="FEED // LIVE" Foreground="#6DFFB3" FontFamily="Consolas" FontSize="10"/>
          </StackPanel>
          <Button x:Name="BtnCoreToggle" Grid.Column="2" Content="启动内核" MinWidth="142" Height="54" Background="#64251F" BorderBrush="#FF6B35" BorderThickness="1" AutomationProperties.Name="启动或停止本项目内核"/>
        </Grid>
      </Border>
      <Grid Grid.Row="1" Margin="0,14,0,14">
        <Grid.ColumnDefinitions><ColumnDefinition Width="1.35*"/><ColumnDefinition Width="0.85*"/></Grid.ColumnDefinitions>
        <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <UniformGrid Grid.ColumnSpan="2" Columns="4" Margin="0,0,0,12">
          <Border Background="#160F18" BorderBrush="#6B2730" BorderThickness="1" Padding="13" Margin="0,0,5,0"><StackPanel><TextBlock Text="01 / GOOGLE" Foreground="#FF6B35" FontFamily="Consolas" FontSize="12"/><TextBlock x:Name="GoogleState" Text="锚定状态未知" FontSize="19" Foreground="#FFB347" Margin="0,9,0,3"/><TextBlock x:Name="GoogleDetail" Text="等待验证" Foreground="#B9AFCA" FontSize="11" TextWrapping="Wrap"/></StackPanel></Border>
          <Border Background="#120F18" BorderBrush="#52305E" BorderThickness="1" Padding="13" Margin="5,0,5,0"><StackPanel><TextBlock Text="02 / CLAUDE" Foreground="#CF78FF" FontFamily="Consolas" FontSize="12"/><TextBlock Text="使用出口未登记" FontSize="19" Foreground="#FFB347" Margin="0,9,0,3"/><TextBlock x:Name="ClaudeDetail" Text="等待网关证据" Foreground="#B9AFCA" FontSize="11" TextWrapping="Wrap"/></StackPanel></Border>
          <Border Background="#10141A" BorderBrush="#235A67" BorderThickness="1" Padding="13" Margin="5,0,5,0"><StackPanel><TextBlock Text="03 / FLOW" Foreground="#6DDBFF" FontFamily="Consolas" FontSize="12"/><TextBlock x:Name="FlowState" Text="网关待命" FontSize="19" Foreground="#6DDBFF" Margin="0,9,0,3"/><TextBlock x:Name="FlowDetail" Text="实时消息未接入" Foreground="#A9C4CF" FontSize="11" TextWrapping="Wrap"/></StackPanel></Border>
          <Border Background="#18130E" BorderBrush="#80511E" BorderThickness="1" Padding="13" Margin="5,0,0,0"><StackPanel><TextBlock Text="04 / MOBILE" Foreground="#FFB347" FontFamily="Consolas" FontSize="12"/><TextBlock Text="告警未接入" FontSize="19" Foreground="#FFB347" Margin="0,9,0,3"/><TextBlock Text="不伪造送达回执" Foreground="#C0B4A5" FontSize="11" TextWrapping="Wrap"/></StackPanel></Border>
        </UniformGrid>
        <Border Grid.Row="1" Grid.Column="0" Background="#0E1117" BorderBrush="#3C5366" BorderThickness="1" Padding="12" Margin="0,0,7,0">
          <Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
            <Grid><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions><StackPanel><TextBlock Text="LIVE INTELLIGENCE STREAM" Foreground="#6DDBFF" FontFamily="Consolas" FontSize="12" FontWeight="Bold"/><TextBlock x:Name="FeedSummaryText" Text="正在整理网关消息…" Foreground="#78909C" FontSize="11" Margin="0,4,0,0"/></StackPanel><TextBlock Grid.Column="1" x:Name="FeedFilterText" Text="ALL SIGNALS" Foreground="#FF6B35" FontFamily="Consolas" FontSize="10" VerticalAlignment="Center"/></Grid>
            <ListBox Grid.Row="1" x:Name="MessageFeed" Background="Transparent" BorderThickness="0" Margin="0,8,0,4" Foreground="#E5E9F0" ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
            <TextBlock Grid.Row="2" x:Name="FeedFooterText" Text="消息已去重 · 原始日志不会直接展示" Foreground="#63717D" FontSize="10" Margin="0,6,0,0"/>
          </Grid>
        </Border>
        <Border Grid.Row="1" Grid.Column="1" Background="#160F18" BorderBrush="#7A3440" BorderThickness="1" Padding="14" Margin="7,0,0,0">
          <Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
            <StackPanel><TextBlock Text="ENGINEER // DIRECTIVE" Foreground="#FF6B35" FontFamily="Consolas" FontSize="12" FontWeight="Bold"/><TextBlock Text="告诉工程师你想看什么，面板自动调整" Foreground="#C79A8D" FontSize="11" Margin="0,5,0,0" TextWrapping="Wrap"/></StackPanel>
            <StackPanel Grid.Row="1" Margin="0,15,0,10"><TextBlock Text="例如：不显示错误重试；显示最近出视频的日志；恢复默认" Foreground="#8E7774" FontSize="11" TextWrapping="Wrap"/><TextBox x:Name="EngineerInput" Height="76" Margin="0,9,0,8" AcceptsReturn="True" TextWrapping="Wrap"/><Button x:Name="BtnEngineerApply" Content="应用工程师指令" Height="34" Background="#64251F" BorderBrush="#FF6B35" BorderThickness="1"/></StackPanel>
            <StackPanel Grid.Row="2"><TextBlock x:Name="EngineerStatus" Text="ENGINEER STATUS // 本地规则待命" Foreground="#6DFFB3" FontFamily="Consolas" FontSize="10" TextWrapping="Wrap"/><Button x:Name="BtnGlmDigest" Content="生成一段 GLM 常态汇报（预留）" Margin="0,9,0,0" Height="30" Background="#2B1D3B"/></StackPanel>
          </Grid>
        </Border>
      </Grid>
      <Border Grid.Row="2" Background="#18110E" BorderBrush="#80511E" BorderThickness="1" Padding="12" CornerRadius="2">
        <Grid><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions><TextBlock x:Name="CockpitTicker" Text="SYSTEM // 正在等待网关事件" Foreground="#FFB347" FontFamily="Consolas" FontSize="11" VerticalAlignment="Center"/><TextBlock Text="F9 ENGINEER · CTRL+D DEBUG" Foreground="#8F7772" FontFamily="Consolas" FontSize="10" Grid.Column="1" VerticalAlignment="Center"/></Grid>
      </Border>
    </Grid>
    <Grid x:Name="DebugHost" Visibility="Collapsed">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#1B1B20" CornerRadius="10" Padding="12,10">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
          <Ellipse x:Name="Dot" Width="9" Height="9" Fill="#B7FF00" VerticalAlignment="Center"/>
          <TextBlock Text="APH // DEBUG OPS" Margin="8,0,10,0" FontFamily="Consolas" FontWeight="Bold" Foreground="#B7FF00" VerticalAlignment="Center"/>
          <TextBlock x:Name="KernelText" Text="正在检测内核…" Margin="8,0,0,0" VerticalAlignment="Center"/>
          <Button x:Name="BtnHealth" Content="[ 自检 ]" Margin="16,0,0,0" Background="#283A1A"/>
          <Button x:Name="BtnStartCore" Content="[ 启动 ]" Margin="6,0,0,0" Background="#5B3A12"/>
          <Button x:Name="BtnStopCore" Content="[ 停止 ]" Margin="6,0,0,0" Background="#4A1D25"/>
          <Button x:Name="BtnMaintain" Content="[ 调试面板 ]" Margin="6,0,0,0"/>
          <TextBlock Text="场景靶场" Opacity="0.65" VerticalAlignment="Center" Margin="12,0,6,0"/>
          <ComboBox x:Name="CmbScene" Width="185" VerticalAlignment="Center"/>
          <Button x:Name="BtnCopyScenePool" Content="⚡ 复制场景池" Margin="8,0,0,0" Background="#1B432C"/>
        </StackPanel>
        <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
          <TextBlock Text="复制格式" Opacity="0.65" VerticalAlignment="Center"/>
          <ComboBox x:Name="CmbFormat" Width="200" Margin="8,0,0,0"/>
        </StackPanel>
      </Grid>
    </Border>

    <!-- 视图切换：一个面板，两个视图 -->
    <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="2,10,0,0">
      <Button x:Name="BtnViewExport" Content="📦 出口取用" Background="#2C3F63"/>
      <Button x:Name="BtnViewGuard"  Content="🛡 巡检风控" Margin="6,0,0,0"/>
      <TextBlock x:Name="ViewHint" Margin="14,0,0,0" VerticalAlignment="Center" Opacity="0.55" FontSize="11"
                 Text="取用出口配置；或对全网 125 个出口做体检、看账号粘性锚定与风控状态"/>
    </StackPanel>

    <!-- ============ 视图一：出口取用 ============ -->
    <Grid Grid.Row="2" x:Name="ViewExport" Margin="0,6,0,0">
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- 手机/局域网免软件智能分流卡片 -->
      <Border Grid.Row="0" Background="#162232" BorderBrush="#254263" BorderThickness="1" CornerRadius="8" Padding="12,8" Margin="0,2,0,0">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
            <TextBlock Text="📱" FontSize="14" VerticalAlignment="Center"/>
            <TextBlock Text="手机/局域网智能分流总线" FontWeight="SemiBold" Foreground="#7FB2FF" Margin="8,0,0,0" VerticalAlignment="Center"/>
            <Border Background="#1F3652" CornerRadius="4" Padding="6,2" Margin="10,0,0,0">
              <TextBlock Text="192.168.0.107:39999" FontFamily="Consolas" FontWeight="SemiBold" Foreground="#A2D2FF" VerticalAlignment="Center"/>
            </Border>
            <TextBlock Text="(HTTP/SOCKS5混合 · 125节点自动选优 · 坏了秒切 · 国内直连)" Opacity="0.75" FontSize="11" Margin="8,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
            <TextBlock x:Name="PhoneStatusText" Text="手机状态未验证" FontSize="11" Foreground="#FFBA68" Margin="0,0,10,0" VerticalAlignment="Center"/>
            <Button x:Name="BtnCopyPhoneProxy" Content="复制代理地址" Background="#203E61" Padding="10,4" Margin="4,0,0,0"/>
            <Button x:Name="BtnPhoneCmd" Content="挂载命令" Background="#283547" Padding="10,4" Margin="4,0,0,0"/>
          </StackPanel>
        </Grid>
      </Border>

      <Grid Grid.Row="1" Margin="0,10,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0" Orientation="Horizontal">
          <TextBlock Text="筛选" Opacity="0.65" VerticalAlignment="Center"/>
          <ComboBox x:Name="CmbFilter" Width="185" Margin="8,0,0,0"/>
        </StackPanel>
        <TextBlock Grid.Column="1" x:Name="CountText" Margin="16,0,0,0" Opacity="0.75" VerticalAlignment="Center"/>
        <TextBox Grid.Column="2" x:Name="TxtSearch" Margin="16,0,10,0" VerticalAlignment="Center"/>
        <StackPanel Grid.Column="3" Orientation="Horizontal">
          <Button x:Name="BtnExpand" Content="全部展开"/>
          <Button x:Name="BtnCollapse" Content="全部折叠" Margin="6,0,0,0"/>
        </StackPanel>
      </Grid>

      <Border Grid.Row="2" Background="#18181C" CornerRadius="10" Padding="4">
        <ScrollViewer x:Name="Scroll" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
          <StackPanel x:Name="Groups" Margin="6"/>
        </ScrollViewer>
      </Border>

      <TextBlock Grid.Row="3" x:Name="StatusText" Margin="4,8,0,0" Opacity="0.6" TextWrapping="Wrap"/>
    </Grid>

    <!-- ============ 视图二：巡检风控 ============ -->
    <Grid Grid.Row="2" x:Name="ViewGuard" Margin="0,6,0,0" Visibility="Collapsed">
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <UniformGrid Grid.Row="0" Rows="1" Columns="5" Margin="0,2,0,0">
        <Border Background="#1F1F25" CornerRadius="9" Padding="12,9" Margin="0,0,8,0">
          <StackPanel>
            <TextBlock Text="全网端口" Opacity="0.6" FontSize="11"/>
            <TextBlock x:Name="GSumTotal" Text="—" FontSize="20" FontWeight="SemiBold" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>
        <Border Background="#1B2A22" CornerRadius="9" Padding="12,9" Margin="0,0,8,0">
          <StackPanel>
            <TextBlock Text="双通存活" Opacity="0.6" FontSize="11"/>
            <TextBlock x:Name="GSumAlive" Text="—" FontSize="20" FontWeight="SemiBold" Foreground="#5FD08A" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>
        <Border Background="#2A1D1D" CornerRadius="9" Padding="12,9" Margin="0,0,8,0">
          <StackPanel>
            <TextBlock Text="不通端口" Opacity="0.6" FontSize="11"/>
            <TextBlock x:Name="GSumDead" Text="—" FontSize="20" FontWeight="SemiBold" Foreground="#FF6B6B" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>
        <Border Background="#1F1F25" CornerRadius="9" Padding="12,9" Margin="0,0,8,0">
          <StackPanel>
            <TextBlock Text="Gemini 纯净可用" Opacity="0.6" FontSize="11"/>
            <TextBlock x:Name="GSumPure" Text="—" FontSize="20" FontWeight="SemiBold" Foreground="#7FB2FF" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>
        <Border Background="#1F1F25" CornerRadius="9" Padding="12,9">
          <StackPanel>
            <TextBlock Text="账号粘性锚定" Opacity="0.6" FontSize="11"/>
            <TextBlock x:Name="GSumBind" Text="—" FontSize="20" FontWeight="SemiBold" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>
      </UniformGrid>

      <Border Grid.Row="1" Background="#1F1F25" CornerRadius="10" Padding="12,10" Margin="0,10,0,0">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <StackPanel Grid.Row="0" Orientation="Horizontal" Margin="2,0,0,6">
            <TextBlock Text="🔒 账号粘性锚定" FontWeight="SemiBold" Foreground="#7FB2FF"/>
            <TextBlock Text="已绑定的出口端口非确凿物理故障绝不切换，杜绝 IP 漂移封号" Opacity="0.6" FontSize="11" Margin="10,1,0,0"/>
          </StackPanel>
          <ListView Grid.Row="1" x:Name="LvBind" Height="205" FontSize="12">
            <ListView.View>
              <GridView>
                <GridViewColumn Header="账号" Width="245" DisplayMemberBinding="{Binding Email}"/>
                <GridViewColumn Header="端口" Width="70"  DisplayMemberBinding="{Binding PortText}"/>
                <GridViewColumn Header="绑定节点" Width="255" DisplayMemberBinding="{Binding ProxyName}"/>
                <GridViewColumn Header="状态" Width="185">
                  <GridViewColumn.CellTemplate>
                    <DataTemplate>
                      <TextBlock Text="{Binding Status}" Foreground="{Binding StatusBrush}" FontWeight="SemiBold"/>
                    </DataTemplate>
                  </GridViewColumn.CellTemplate>
                </GridViewColumn>
              </GridView>
            </ListView.View>
          </ListView>
        </Grid>
      </Border>

      <Grid Grid.Row="2" Margin="0,10,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <Button Grid.Column="0" x:Name="BtnGuardScan" Content="🔍 开始全网巡检" Background="#23375C"/>
        <Button Grid.Column="1" x:Name="BtnGuardFill" Content="⚡ 充盈备选池" Margin="6,0,0,0" Background="#3A2A17"/>
        <StackPanel Grid.Column="2" Orientation="Horizontal" Margin="16,0,0,0">
          <TextBlock Text="筛选" Opacity="0.65" VerticalAlignment="Center"/>
          <ComboBox x:Name="CmbGuardFilter" Width="190" Margin="8,0,0,0" SelectedIndex="0">
            <ComboBoxItem Content="全部端口"/>
            <ComboBoxItem Content="仅存活"/>
            <ComboBoxItem Content="仅不通"/>
            <ComboBoxItem Content="仅 Gemini 纯净可用"/>
            <ComboBoxItem Content="仅账号绑定"/>
            <ComboBoxItem Content="仅备选池"/>
          </ComboBox>
        </StackPanel>
        <TextBox Grid.Column="3" x:Name="TxtGuardSearch" Margin="16,0,10,0" VerticalAlignment="Center"/>
        <TextBlock Grid.Column="4" x:Name="GuardCountText" VerticalAlignment="Center" Opacity="0.75"/>
      </Grid>

      <Border Grid.Row="3" Background="#18181C" CornerRadius="10" Padding="6">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <ListView Grid.Row="0" x:Name="LvGuard" FontSize="12">
            <ListView.View>
              <GridView>
                <GridViewColumn Header="端口" Width="62" DisplayMemberBinding="{Binding Port}"/>
                <GridViewColumn Header="品牌" Width="58">
                  <GridViewColumn.CellTemplate>
                    <DataTemplate>
                      <TextBlock Text="{Binding Brand}" Foreground="{Binding BrandBrush}" FontWeight="SemiBold"/>
                    </DataTemplate>
                  </GridViewColumn.CellTemplate>
                </GridViewColumn>
                <GridViewColumn Header="节点名称" Width="250" DisplayMemberBinding="{Binding Name}"/>
                <GridViewColumn Header="落地地区" Width="150" DisplayMemberBinding="{Binding Country}"/>
                <GridViewColumn Header="风控" Width="115">
                  <GridViewColumn.CellTemplate>
                    <DataTemplate>
                      <TextBlock Text="{Binding Risk}" Foreground="{Binding RiskBrush}"/>
                    </DataTemplate>
                  </GridViewColumn.CellTemplate>
                </GridViewColumn>
                <GridViewColumn Header="状态" Width="175">
                  <GridViewColumn.CellTemplate>
                    <DataTemplate>
                      <TextBlock Text="{Binding Status}" Foreground="{Binding StatusBrush}" FontWeight="SemiBold"/>
                    </DataTemplate>
                  </GridViewColumn.CellTemplate>
                </GridViewColumn>
                <GridViewColumn Header="出口 IP" Width="140" DisplayMemberBinding="{Binding ExitIp}"/>
              </GridView>
            </ListView.View>
          </ListView>
          <ProgressBar Grid.Row="1" x:Name="GuardBar" Margin="4,8,4,2" Minimum="0" Maximum="125" Value="0"/>
        </Grid>
      </Border>

      <TextBlock Grid.Row="4" x:Name="GuardStatusText" Margin="4,8,0,0" Opacity="0.7" TextWrapping="Wrap"/>
    </Grid>
    </Grid>
  </Grid>
</Window>
'@

$win = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $xaml))

# 应用图标：窗口（标题栏/任务栏）与托盘共用 assets\app.ico
$script:IconPath = Join-Path $Dir 'assets\app.ico'
if (Test-Path -LiteralPath $script:IconPath) {
    try {
        $fs = [System.IO.File]::OpenRead($script:IconPath)
        try {
            $dec = [Windows.Media.Imaging.BitmapDecoder]::Create(
                $fs,
                [Windows.Media.Imaging.BitmapCreateOptions]::PreservePixelFormat,
                [Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
            $frame = @($dec.Frames) | Sort-Object -Property PixelWidth -Descending | Select-Object -First 1
            if ($frame) { $win.Icon = $frame }
        } finally { $fs.Dispose() }
    } catch { Write-PanelEvent 'icon-failed' $_.Exception.Message }
}

$applyDarkTitle = {
    try {
        $helper = New-Object System.Windows.Interop.WindowInteropHelper($win)
        if ($helper.Handle -ne [IntPtr]::Zero) {
            [Win11Dwm]::EnableDarkMode($helper.Handle, 0x00161313, 0x00ECE9E9)
        }
    } catch { }
}
$win.Add_SourceInitialized($applyDarkTitle)
$win.Add_Loaded($applyDarkTitle)
$win.Add_Activated($applyDarkTitle)

$ViewCockpit = $win.FindName('ViewCockpit')
$DebugHost = $win.FindName('DebugHost')
$BtnCoreToggle = $win.FindName('BtnCoreToggle')
$CockpitState = $win.FindName('CockpitState')
$CockpitDetail = $win.FindName('CockpitDetail')
$GoogleState = $win.FindName('GoogleState')
$GoogleDetail = $win.FindName('GoogleDetail')
$ClaudeDetail = $win.FindName('ClaudeDetail')
$FlowState = $win.FindName('FlowState')
$FlowDetail = $win.FindName('FlowDetail')
$CockpitClock = $win.FindName('CockpitClock')
$CockpitTicker = $win.FindName('CockpitTicker')
$FeedSummaryText = $win.FindName('FeedSummaryText')
$MessageFeed = $win.FindName('MessageFeed')
$EngineerInput = $win.FindName('EngineerInput')
$BtnEngineerApply = $win.FindName('BtnEngineerApply')
$EngineerStatus = $win.FindName('EngineerStatus')
$BtnGlmDigest = $win.FindName('BtnGlmDigest')
$script:CoreAction = $null
$script:CoreActionError = ''
function Set-PanelMode([bool]$debug) {
    $DebugHost.Visibility = if ($debug) { 'Visible' } else { 'Collapsed' }
    $ViewCockpit.Visibility = if ($debug) { 'Collapsed' } else { 'Visible' }
}
$win.Add_PreviewKeyDown({
    param($sender, $e)
    if ($e.Key -eq 'F9') {
        if ($DebugHost.Visibility -eq 'Visible') { $EngineerInput.Focus() } else { $EngineerInput.Focus() }
        $e.Handled = $true
    } elseif ($e.Key -eq 'D' -and ([Windows.Input.Keyboard]::Modifiers -band [Windows.Input.ModifierKeys]::Control)) {
        Set-PanelMode ($DebugHost.Visibility -ne 'Visible'); $e.Handled = $true
    } elseif ($e.Key -eq 'Escape' -and $DebugHost.Visibility -eq 'Visible') {
        Set-PanelMode $false; $e.Handled = $true
    }
})
$Dot         = $win.FindName('Dot')
$KernelText  = $win.FindName('KernelText')
$StatusText  = $win.FindName('StatusText')
$CountText   = $win.FindName('CountText')
$Groups      = $win.FindName('Groups')
$Scroll      = $win.FindName('Scroll')
$BtnHealth   = $win.FindName('BtnHealth')
$BtnMaintain = $win.FindName('BtnMaintain')
$BtnStartCore = $win.FindName('BtnStartCore')
$BtnStopCore = $win.FindName('BtnStopCore')
$CmbScene    = $win.FindName('CmbScene')
$BtnCopyScenePool = $win.FindName('BtnCopyScenePool')
$BtnExpand   = $win.FindName('BtnExpand')
$BtnCollapse = $win.FindName('BtnCollapse')
$CmbFormat   = $win.FindName('CmbFormat')
$CmbFilter   = $win.FindName('CmbFilter')
$TxtSearch   = $win.FindName('TxtSearch')
$BtnCopyPhoneProxy = $win.FindName('BtnCopyPhoneProxy')
$BtnPhoneCmd       = $win.FindName('BtnPhoneCmd')
$PhoneStatusText   = $win.FindName('PhoneStatusText')

# 点窗口关闭只隐藏面板；托盘菜单的「退出面板」才真正结束进程，内核独立运行。
$script:ExitRequested = $false
$script:Tray = New-Object System.Windows.Forms.NotifyIcon
$script:Tray.Icon = if ($script:IconPath -and (Test-Path -LiteralPath $script:IconPath)) {
    New-Object System.Drawing.Icon($script:IconPath)
} else {
    [System.Drawing.SystemIcons]::Application
}
$script:Tray.Text = 'AgentProxyHub（出口取用 / 巡检风控）'
$trayMenu = New-Object System.Windows.Forms.ContextMenuStrip
$openItem = $trayMenu.Items.Add('打开面板')
$exitItem = $trayMenu.Items.Add('退出面板（内核继续运行）')
$script:Tray.ContextMenuStrip = $trayMenu
$openPanel = {
    $win.ShowInTaskbar = $true
    $win.Show()
    $win.WindowState = [Windows.WindowState]::Normal
    $win.Activate() | Out-Null
    Write-PanelEvent 'shown'
}
$openItem.Add_Click($openPanel)
$debugItem = $trayMenu.Items.Insert(1, (New-Object Windows.Forms.ToolStripMenuItem('调试面板（Ctrl+D）')))
# Insert returns void; locate the inserted menu item explicitly.
$trayMenu.Items[1].Add_Click({ & $openPanel; Set-PanelMode $true })
$homeItem = $trayMenu.Items.Insert(2, (New-Object Windows.Forms.ToolStripMenuItem('返回驾驶舱')))
$trayMenu.Items[2].Add_Click({ & $openPanel; Set-PanelMode $false })
$script:Tray.Add_MouseClick({
    param($sender, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) { & $openPanel }
})
$script:Tray.Add_DoubleClick($openPanel)
$exitItem.Add_Click({
    $script:ExitRequested = $true
    Write-PanelEvent 'exit-menu'
    $win.Close()
})
$win.Add_Closing({
    param($sender, $e)
    if (-not $script:ExitRequested) {
        $e.Cancel = $true
        $win.Hide()
        $win.ShowInTaskbar = $false
        Write-PanelEvent 'hidden-to-tray'
    }
})
$script:Tray.Visible = $true
$script:ShowTimer = New-Object Windows.Threading.DispatcherTimer
$script:ShowTimer.Interval = [TimeSpan]::FromMilliseconds(300)
$script:ShowTimer.Add_Tick({
    if ($script:ShowSignal.WaitOne(0)) { & $openPanel }
    if ($script:GuardSignal.WaitOne(0)) {
        & $openPanel
        Switch-View 'Guard'
    }
})
$script:ShowTimer.Start()

foreach ($k in $script:Formats.Keys) { [void]$CmbFormat.Items.Add($k) }
$CmbFormat.SelectedIndex = 0
$filters = @(
    '✨ 反重力 & Flow 优质推荐 (S+A+B)',
    '👑 仅看 S 级纯净推荐',
    '🌟 仅看 A 级优质原生',
    '🐝 仅看蜂窝优质',
    '⭐ 仅看星辰优质',
    '全部出口 (含冷门与隔离区)',
    '⚠️ Google 已送中 (避坑)'
)
foreach ($f in $filters) { [void]$CmbFilter.Items.Add($f) }
$CmbFilter.SelectedIndex = 0
$TxtSearch.Text = '搜索地区 / 城市 / 端口 / IP'

# ---------------- 数据与工具 ----------------
$script:Nodes = @()
$script:Lat = @{}
$script:Secret = ''
$script:ProfilePath = ''
$script:LastWrite = $null
$script:ExpandedInit = $false
$script:EngineerRules = @{ hidden = @(); focus = @(); updatedAt = $null }
$script:EngineerRulesPath = Get-RunFile 'cockpit_rules.json'
try {
    if (Test-Path -LiteralPath $script:EngineerRulesPath) {
        $savedRules = Get-Content -LiteralPath $script:EngineerRulesPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($savedRules.hidden) { $script:EngineerRules.hidden = @($savedRules.hidden) }
        if ($savedRules.focus) { $script:EngineerRules.focus = @($savedRules.focus) }
    }
} catch { }
$script:MessageSeen = @{}
$script:LastGatewayLogLength = 0
$script:GatewayLogSources = @(
    [pscustomobject]@{ Name='APH'; Path=(Join-Path $Dir 'logs\panel.log'); Kind='panel' },
    [pscustomobject]@{ Name='FengWoBridge'; Path='D:\Program Files\FengWoBridge\logs\panel.log'; Kind='panel' },
    [pscustomobject]@{ Name='Flow'; Path='D:\GitHub\Flow-Tools\logs\gateway.log'; Kind='flow' },
    [pscustomobject]@{ Name='Antigravity'; Path='D:\ProgramData\AntigravityTools\logs\gateway.log'; Kind='antigravity' }
)

function Convert-GatewayLine([string]$source, [string]$line, [string]$kindHint) {
    if ([string]::IsNullOrWhiteSpace($line)) { return $null }
    $clean = ($line -replace '[\r\n]+', ' ').Trim()
    # 去时间戳、PID和技术前缀，只保留人类可读的事件主体。
    $clean = $clean -replace '^\[[^\]]+\]\s*', ''
    $clean = $clean -replace '^\d{4}-\d{2}-\d{2}[T\s][^\s]+\s+', ''
    $parts = $clean -split '\s+', 4
    $kind = if ($parts.Count -ge 3 -and $parts[2] -match '^[A-Za-z][A-Za-z0-9_-]*$') { $parts[2].ToUpperInvariant() } else { $kindHint.ToUpperInvariant() }
    $detail = if ($parts.Count -ge 4) { $parts[3] } else { $clean }
    $detail = $detail -replace '(?i)(token|secret|authorization|cookie)=\S+', '$1=[已脱敏]'
    $tone = if ($clean -match '(?i)error|exception|fail|fatal|alert') { 'alert' } elseif ($clean -match '(?i)warn|retry|timeout|degrad') { 'warn' } else { 'normal' }
    return [pscustomobject]@{ Source=$source; Category=$kind; Detail=$detail; Tone=$tone }
}

function Import-GatewayDigest {
    foreach ($source in $script:GatewayLogSources) {
        if (-not (Test-Path -LiteralPath $source.Path)) { continue }
        try {
            foreach ($line in @(Get-Content -LiteralPath $source.Path -Encoding UTF8 -Tail 12)) {
                $event = Convert-GatewayLine $source.Name $line $source.Kind
                if ($event) { Add-CockpitMessage "$($event.Source)/$($event.Category)" $event.Detail $event.Tone }
            }
        } catch { }
    }
}

function Add-CockpitMessage([string]$category, [string]$text, [string]$tone = 'normal') {
    if (-not $MessageFeed -or [string]::IsNullOrWhiteSpace($text)) { return }
    $clean = ($text -replace '[\r\n]+', ' ').Trim()
    if ($clean.Length -gt 180) { $clean = $clean.Substring(0,177) + '...' }
    $finger = "$category|$clean"
    if ($script:MessageSeen.ContainsKey($finger)) { return }
    $script:MessageSeen[$finger] = (Get-Date)
    if ($script:MessageSeen.Count -gt 200) {
        $old = $script:MessageSeen.GetEnumerator() | Sort-Object Value | Select-Object -First 50
        foreach ($x in $old) { $script:MessageSeen.Remove($x.Key) }
    }
    foreach ($rule in @($script:EngineerRules.hidden)) {
        if ($clean -like "*$rule*") { return }
    }
    $item = New-Object Windows.Controls.ListBoxItem
    $item.Content = "[$category] $clean"
    $item.ToolTip = '来源已归一化；原始日志不会直接展示'
    $feedColor = if ($tone -eq 'warn') { '#FFB347' } elseif ($tone -eq 'alert') { '#FF6B7D' } else { '#D6E4EE' }
    $item.Foreground = New-GBrush $feedColor
    $item.Padding = [Windows.Thickness]::new(4,5,4,5)
    $item.FontFamily = 'Consolas'
    [void]$MessageFeed.Items.Insert(0, $item)
    while ($MessageFeed.Items.Count -gt 12) { $MessageFeed.Items.RemoveAt($MessageFeed.Items.Count - 1) }
    $FeedSummaryText.Text = "已整理 $($MessageFeed.Items.Count) 条 · 原始日志已转译"
    $CockpitTicker.Text = "$category // $clean"
}

function Apply-EngineerDirective([string]$directive) {
    $d = ($directive -replace '[\r\n]+', ' ').Trim()
    if (-not $d) { return }
    if ($d -match '不显示|隐藏|屏蔽') {
        $m = [regex]::Match($d, '(?:不显示|隐藏|屏蔽)(?:掉|这个|这类)?\s*([\p{L}\p{N}_-]{2,24})')
        if ($m.Success) { $script:EngineerRules.hidden += $m.Groups[1].Value; $EngineerStatus.Text = "ENGINEER // 已隐藏关键词：$($m.Groups[1].Value)" }
        else { $EngineerStatus.Text = 'ENGINEER // 请说清要隐藏的关键词' }
    } elseif ($d -match '显示|查看|关注') {
        if ($d -match '视频|出片|生成') { $script:EngineerRules.focus = @('视频','出片','生成'); $EngineerStatus.Text = 'ENGINEER // 已切换到视频/出片情报视图' }
        else { $EngineerStatus.Text = 'ENGINEER // 已更新关注主题' }
    } elseif ($d -match '恢复|默认|清除') {
        $script:EngineerRules = @{ hidden=@(); focus=@(); updatedAt=(Get-Date) }; $EngineerStatus.Text = 'ENGINEER // 已恢复默认显示规则'
    } else { $EngineerStatus.Text = 'ENGINEER // 指令已记录，GLM 摘要接口待接入' }
    try { $script:EngineerRules | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $script:EngineerRulesPath -Encoding UTF8 } catch { }
    Add-CockpitMessage 'ENGINEER' $EngineerStatus.Text
}

function Pump {
    [Windows.Threading.Dispatcher]::CurrentDispatcher.Invoke(
        [action]{}, [Windows.Threading.DispatcherPriority]::Background)
}

function Get-BridgeInfo {
    $f = Join-Path $Dir 'bridge.json'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    try { return (Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Get-Secret {
    $b = Get-BridgeInfo
    if ($b -and $b.secret) { return $b.secret }
    return ''
}

function Get-ProfileInfo {
    $b = Get-BridgeInfo
    if (-not $b -or -not $b.profilePath) { return $null }
    $p = $b.profilePath
    if (-not (Test-Path -LiteralPath $p)) { return @{ Path = $p; Write = $null } }
    return @{ Path = $p; Write = (Get-Item -LiteralPath $p).LastWriteTime }
}

function Get-OwnedCoreProcesses {
    $paths = @((Join-Path $Dir 'bin\mihomo.exe'), (Join-Path $Dir 'mihomo.exe'))
    @(Get-Process mihomo -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and ($paths -contains $_.Path) } catch { $false }
    })
}
function Test-Kernel {
    return (@(Get-OwnedCoreProcesses).Count -gt 0)
}

function Invoke-Script([string]$file, [string[]]$extra = @()) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', (Get-CoreFile $file)) + $extra
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = ($argList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [Diagnostics.Process]::Start($psi)
    $out = $p.StandardOutput.ReadToEnd()
    $err = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    return @{ Code = $p.ExitCode; Out = $out; Err = $err }
}
# 异步启动引擎脚本（不阻塞 UI）
function Start-ScriptAsync([string]$file, [string[]]$extra = @()) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', (Get-CoreFile $file)) + $extra
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = ($argList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    return [Diagnostics.Process]::Start($psi)
}

function Load-Nodes {
    $f = Get-RunFile 'nodes.json'
    if (-not (Test-Path -LiteralPath $f)) { return $false }
    $j = Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json
    $script:Nodes = @($j.nodes)
    $script:DataStamp = $j.generatedAt
    $script:AliveTotal = $j.alive
    return $true
}

# 并发测速：80 个请求同时发出（串行要几分钟）
# 并发测速（分段式：先发请求，再由定时器收割，UI 不卡）
function Start-Latency {
    $script:Lat = @{}
    $script:LatDone = $false
    $script:LatClient = $null
    $script:LatTasks = $null
    $script:LatNames = $null
    $script:LatStarted = $null
    if (-not (Test-Kernel)) { $script:LatDone = $true; return }
    $secret = Get-Secret
    if (-not $secret) { $script:LatDone = $true; return }
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(12)
    $client.DefaultRequestHeaders.Add('Authorization', "Bearer $secret")
    $names = New-Object 'System.Collections.Generic.List[string]'
    $tasks = New-Object 'System.Collections.Generic.List[object]'
    foreach ($n in $script:Nodes) {
        $names.Add($n.name)
        $u = "http://127.0.0.1:21909/proxies/$($n.name)/delay?timeout=3000&url=http%3A%2F%2Fwww.gstatic.com%2Fgenerate_204"
        try { $tasks.Add($client.GetStringAsync($u)) } catch { $tasks.Add($null) }
    }
    $script:LatClient = $client
    $script:LatTasks = $tasks
    $script:LatNames = $names
    $script:LatStarted = [DateTime]::Now
}
function Poll-Latency {
    if ($script:LatDone) { return }
    $elapsed = (([DateTime]::Now) - $script:LatStarted).TotalMilliseconds
    $allDone = $true
    foreach ($t in $script:LatTasks) { if ($t -and -not $t.IsCompleted) { $allDone = $false; break } }
    if (-not $allDone -and $elapsed -lt 26000) { return }
    $ok = 0
    for ($i = 0; $i -lt $script:LatTasks.Count; $i++) {
        $t = $script:LatTasks[$i]
        if ($t -and $t.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) {
            try {
                $d = ($t.Result | ConvertFrom-Json).delay
                if ($d -gt 0) { $script:Lat[$script:LatNames[$i]] = [int]$d; $ok++ }
            } catch { }
        }
    }
    try { $script:LatClient.Dispose() } catch { }
    $script:LatClient = $null; $script:LatTasks = $null; $script:LatNames = $null
    $script:LatDone = $true
    $script:LatOk = $ok
}

function Get-Tags($n) {
    $t = New-Object 'System.Collections.Generic.List[string]'
    if ($n.orig -match '解锁') { $t.Add('解锁') }
    if ($n.orig -match '原生') { $t.Add('原生') }
    if ($n.orig -match '专线') { $t.Add('专线') }
    if ($n.orig -match '动态') { $t.Add('动态') }
    if ($n.orig -match '家宽') { $t.Add('家宽') }
    if ($n.orig -match 'CF优选') { $t.Add('CF优选') }
    if ($n.kind) { $t.Add($n.kind) }
    return $t
}

function Test-Premium($n) {
    $ms = $script:Lat[$n.name]
    if (-not $ms) { return $false }
    if ($ms -gt 300) { return $false }
    if ($n.kind -ne '机房' -and $n.orig -notmatch '专线') { return $false }
    return $true
}

function Test-Unlocked($n) { return ($n.orig -match '解锁') }
function Test-Native($n) { return ($n.orig -match '原生') }
function Test-Dedicated($n) { return ($n.orig -match '专线') }
function Test-Alive($n) { return [bool]($n.ip -and $script:Lat[$n.name]) }

function Get-Filtered {
    $sel = $CmbFilter.SelectedItem
    $kw = $TxtSearch.Text.Trim()
    if ($kw -eq '搜索地区 / 城市 / 端口 / IP') { $kw = '' }
    $out = foreach ($n in $script:Nodes) {
        $pass = switch ($sel) {
            '✨ 反重力 & Flow 优质推荐 (S+A+B)' { [bool]($n.antigravitySupported) }
            '👑 仅看 S 级纯净推荐'               { $n.healthRating -eq 'S' }
            '🌟 仅看 A 级优质原生'               { $n.healthRating -eq 'A' }
            '🐝 仅看蜂窝优质'                   { ($n.airport -eq '蜂窝') -and [bool]($n.antigravitySupported) }
            '⭐ 仅看星辰优质'                   { ($n.airport -eq '星辰') -and [bool]($n.antigravitySupported) }
            '⚠️ Google 已送中 (避坑)'           { [bool]($n.isSentToChina) }
            '全部出口 (含冷门与隔离区)'          { $true }
            default                             { [bool]($n.antigravitySupported) }
        }
        if (-not $pass) { continue }
        if ($kw) {
            $cn = $null
            if ($n.countryCode) { $cn = $script:RegionCn[$n.countryCode] }
            $hay = "$($n.port) $($n.airport) $($n.countryCode) $cn $($n.country) $($n.city) $($n.ip) $($n.orig) $($n.googleCountry) $($n.aiStatus)"
            if ($hay -notmatch [regex]::Escape($kw)) { continue }
        }
        $n
    }
    return @($out)
}

# ---------------- 行与分组渲染 ----------------
function New-Chip([string]$text, [string]$bg, [string]$fg = '#E9E9EC') {
    $b = New-Object Windows.Controls.Border
    $b.Background = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($bg))
    $b.CornerRadius = [Windows.CornerRadius]::new(3)
    $b.Padding = [Windows.Thickness]::new(6, 1, 6, 1)
    $b.Margin = [Windows.Thickness]::new(0, 0, 5, 0)
    $t = New-Object Windows.Controls.TextBlock
    $t.Text = $text
    $t.FontSize = 11
    $t.Foreground = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($fg))
    $b.Child = $t
    return $b
}

function New-Row($n) {
    $border = New-Object Windows.Controls.Border
    $border.Background = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString('#1F1F25'))
    $border.CornerRadius = [Windows.CornerRadius]::new(6)
    $border.Padding = [Windows.Thickness]::new(10, 6, 10, 6)
    $border.Margin = [Windows.Thickness]::new(18, 0, 0, 4)

    $g = New-Object Windows.Controls.Grid
    foreach ($w in @(106, 150, 130, 74, 0, 74)) {
        $c = New-Object Windows.Controls.ColumnDefinition
        if ($w -gt 0) { $c.Width = [Windows.GridLength]::new($w) } else { $c.Width = [Windows.GridLength]::new(1, [Windows.GridUnitType]::Star) }
        $g.ColumnDefinitions.Add($c)
    }

    $pcol = New-Object Windows.Controls.StackPanel
    $pcol.Orientation = 'Vertical'
    $p = New-Object Windows.Controls.TextBlock
    $p.Text = "$($n.port)"
    $p.Foreground = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString('#7FB2FF'))
    $p.FontFamily = 'Consolas'
    $p.FontWeight = [Windows.FontWeights]::SemiBold
    $pcol.Children.Add($p) | Out-Null

    # 机场来源徽章
    $air = if ($n.airport) { $n.airport } elseif ($n.port -ge 22001) { '星辰' } else { '蜂窝' }
    $airBg = if ($air -eq '星辰') { '#2D2250' } else { '#4A2E18' }
    $airFg = if ($air -eq '星辰') { '#B692FE' } else { '#FFA756' }
    $airChip = New-Chip "[$air]" $airBg $airFg
    $airChip.Margin = [Windows.Thickness]::new(0, 2, 0, 0)
    $pcol.Children.Add($airChip) | Out-Null

    # 健康度评分徽章
    $sc = if ($n.healthScore) { [int]$n.healthScore } else { 0 }
    $rt = if ($n.healthRating) { $n.healthRating } else { 'F' }
    $scBg = if ($sc -ge 90) { '#1B432C' } elseif ($sc -ge 80) { '#183B38' } elseif ($sc -gt 0) { '#423318' } else { '#451717' }
    $scFg = if ($sc -ge 90) { '#5FD08A' } elseif ($sc -ge 80) { '#48CAE4' } elseif ($sc -gt 0) { '#E8C46A' } else { '#FF8B8B' }
    $scText = "$sc分·$rt"
    if ($n.isSentToChina) { $scText = "0分·送中" }
    elseif (-not $n.ip) { $scText = "0分·离线" }
    $chipBorder = New-Chip $scText $scBg $scFg
    $chipBorder.Margin = [Windows.Thickness]::new(0, 2, 0, 0)
    $pcol.Children.Add($chipBorder) | Out-Null

    if ($n.httpPort) {
        $ph = New-Object Windows.Controls.TextBlock
        $ph.Text = "http $($n.httpPort)"
        $ph.FontSize = 10
        $ph.Opacity = 0.55
        $ph.FontFamily = 'Consolas'
        $pcol.Children.Add($ph) | Out-Null
    }
    $pcol.VerticalAlignment = 'Center'
    [Windows.Controls.Grid]::SetColumn($pcol, 0)
    $g.Children.Add($pcol) | Out-Null

    $loc = New-Object Windows.Controls.StackPanel
    $loc.Orientation = 'Vertical'
    $l1 = New-Object Windows.Controls.TextBlock
    $cCode = $n.countryCode
    $cCn = if ($cCode -and $script:RegionCn.ContainsKey($cCode)) { $script:RegionCn[$cCode] } else { $n.country }
    if (-not $cCn -and $n.googleCountry) { $cCn = $n.googleCountry }
    if (-not $cCn) { $cCn = $n.orig -replace '-(专线|原生|vip|解锁|家宽|动态).*', '' }
    $locText = if ($cCn -and $n.city) { "$cCn · $($n.city)" }
               elseif ($cCn) { "$cCn" }
               elseif ($n.ip) { "物理地区解析中" }
               else { "节点离线" }
    $l1.Text = $locText
    $l1.TextTrimming = 'CharacterEllipsis'
    $loc.Children.Add($l1) | Out-Null

    # Google 判定地区显示
    if ($n.googleCountry) {
        $lGoogle = New-Object Windows.Controls.TextBlock
        $gColor = if ($n.antigravitySupported) { '#5FD08A' } elseif ($n.isSentToChina) { '#FF7B7B' } else { '#B0B0BA' }
        $gText = "Google: $($n.googleCountry)"
        if ($n.isSentToChina) { $gText += " (送中)" }
        $lGoogle.Text = $gText
        $lGoogle.FontSize = 11
        $lGoogle.Foreground = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($gColor))
        $lGoogle.TextTrimming = 'CharacterEllipsis'
        $loc.Children.Add($lGoogle) | Out-Null
    }

    $l2 = New-Object Windows.Controls.TextBlock
    $l2.Text = if ($n.isp) { $n.isp } else { '—' }
    $l2.FontSize = 10
    $l2.Opacity = 0.55
    $l2.TextTrimming = 'CharacterEllipsis'
    $loc.Children.Add($l2) | Out-Null

    $loc.VerticalAlignment = 'Center'
    [Windows.Controls.Grid]::SetColumn($loc, 1)
    $g.Children.Add($loc) | Out-Null

    $ip = New-Object Windows.Controls.TextBlock
    $ip.Text = if ($n.ip) { $n.ip } else { '未探测' }
    $ip.FontFamily = 'Consolas'
    $ip.FontSize = 12
    $ip.VerticalAlignment = 'Center'
    if (-not $n.ip) { $ip.Opacity = 0.45 }
    [Windows.Controls.Grid]::SetColumn($ip, 2)
    $g.Children.Add($ip) | Out-Null

    $ms = $script:Lat[$n.name]
    $lat = New-Object Windows.Controls.TextBlock
    if ($ms) {
        $lat.Text = "$ms ms"
        $col = if ($ms -le 150) { '#5FD08A' } elseif ($ms -le 300) { '#E8C46A' } else { '#E08A8A' }
        $lat.Foreground = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($col))
    } else {
        $lat.Text = '—'
        $lat.Opacity = 0.45
    }
    $lat.VerticalAlignment = 'Center'
    $lat.FontSize = 12
    [Windows.Controls.Grid]::SetColumn($lat, 3)
    $g.Children.Add($lat) | Out-Null

    $chips = New-Object Windows.Controls.WrapPanel
    $chips.VerticalAlignment = 'Center'

    # AI 支持徽章优先展示
    if ($n.antigravitySupported) {
        $chips.Children.Add((New-Chip '反重力/Gemini ✅' '#1B432C' '#5FD08A')) | Out-Null
        if ($n.flowSupported) {
            $chips.Children.Add((New-Chip 'Flow ✅' '#182C4A' '#7AB4FF')) | Out-Null
        }
    } elseif ($n.isSentToChina) {
        $chips.Children.Add((New-Chip 'Google送中 ❌' '#451717' '#FF8B8B')) | Out-Null
    } elseif ($n.googleCountry -eq 'China' -or $n.googleCountry -eq 'Hong Kong') {
        $chips.Children.Add((New-Chip '地区不支持 ❌' '#3A2020' '#E09A9A')) | Out-Null
    }

    foreach ($tag in (Get-Tags $n)) {
        $bg = switch ($tag) {
            '解锁'   { '#2E4A33' }
            '原生'   { '#2B3F52' }
            '专线'   { '#3A3350' }
            '动态'   { '#4A3A2A' }
            '家宽'   { '#33383F' }
            '机房'   { '#2B3A44' }
            default  { '#33333A' }
        }
        $chips.Children.Add((New-Chip $tag $bg)) | Out-Null
    }
    [Windows.Controls.Grid]::SetColumn($chips, 4)
    $g.Children.Add($chips) | Out-Null

    $btn = New-Object Windows.Controls.Button
    $btn.Content = '复制'
    $btn.Tag = @{ node = $n; socks = $n.port; http = $n.httpPort }
    $btn.FontSize = 12
    $btn.VerticalAlignment = 'Center'
    [Windows.Controls.Grid]::SetColumn($btn, 5)
    $btn.Add_Click({
        $node = $this.Tag.node
        $fmt = $CmbFormat.SelectedItem
        $text = Format-ProxyEntry $node $fmt
        try { [Windows.Clipboard]::SetText($text) } catch { }
        $this.Content = '已复制'
        $resetTimer = New-Object Windows.Threading.DispatcherTimer
        $resetTimer.Interval = [TimeSpan]::FromMilliseconds(900)
        $resetTimer.Tag = $this
        $resetTimer.Add_Tick({
            param($sender, $eventArgs)
            $sender.Tag.Content = '复制'
            $sender.Stop()
        })
        $script:StatusText.Text = "已复制到剪贴板：$text"
        $resetTimer.Start()
    })
    $g.Children.Add($btn) | Out-Null

    $border.Child = $g
    return $border
}

function Render {
    Update-SceneButton
    $list = Get-Filtered
    $Groups.Children.Clear()

    # 按评级分组定义（S 级、A 级默认展开，其他折叠）
    $groupDefs = @(
        @{
            Key = 'S'
            Title = '👑 S 级 · 极速/专线纯净推荐 (反重力 & Flow 完美支持)'
            Color = '#5FD08A'
            Bg = '#1B432C'
            DefaultExpand = $true
            Match = { param($n) $n.healthRating -eq 'S' }
        },
        @{
            Key = 'A'
            Title = '🌟 A 级 · 优质原生支持 (反重力 & Flow 官方支持区)'
            Color = '#48CAE4'
            Bg = '#183B38'
            DefaultExpand = $true
            Match = { param($n) $n.healthRating -eq 'A' }
        },
        @{
            Key = 'B'
            Title = '⚡ B 级 · 良好可用支持 (家宽/动态 支持区)'
            Color = '#E8C46A'
            Bg = '#423318'
            DefaultExpand = $false
            Match = { param($n) $n.healthRating -eq 'B' }
        },
        @{
            Key = 'Other'
            Title = '🌐 C / D 级 · 其他地区与冷门节点'
            Color = '#B0B0BA'
            Bg = '#2B2B33'
            DefaultExpand = $false
            Match = { param($n) ($n.healthRating -in @('C', 'D')) -and (-not $n.isSentToChina) }
        },
        @{
            Key = 'Sent'
            Title = '⛔ F 级 · 送中与不支持隔离区 (严禁用于反重力/Flow)'
            Color = '#FF8B8B'
            Bg = '#451717'
            DefaultExpand = $false
            Match = { param($n) $n.isSentToChina -or ($n.healthRating -in @('E', 'F')) }
        }
    )

    $kw0 = $TxtSearch.Text.Trim()
    $isSearching = ($kw0 -ne '') -and ($kw0 -ne '搜索地区 / 城市 / 端口 / IP')

    foreach ($gdef in $groupDefs) {
        $items = @($list | Where-Object { & $gdef.Match $_ } |
            Sort-Object { if ($script:Lat[$_.name]) { $script:Lat[$_.name] } else { 9999 } }, { $_.port })
        if ($items.Count -eq 0) { continue }

        $exp = New-Object Windows.Controls.Expander
        # 默认展开 S 级与 A 级；搜索时全展开
        $exp.IsExpanded = $isSearching -or $gdef.DefaultExpand

        $head = New-Object Windows.Controls.StackPanel
        $head.Orientation = 'Horizontal'
        
        $h1 = New-Object Windows.Controls.TextBlock
        $h1.Text = $gdef.Title
        $h1.FontWeight = 'SemiBold'
        $h1.Foreground = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($gdef.Color))
        $head.Children.Add($h1) | Out-Null

        $fwCount = @($items | Where-Object { ($_.airport -eq '蜂窝') -or ($_.port -lt 22001) }).Count
        $xcCount = @($items | Where-Object { ($_.airport -eq '星辰') -or ($_.port -ge 22001) }).Count
        
        $h2 = New-Object Windows.Controls.TextBlock
        $h2.Text = "    $($items.Count) 个出口  (蜂窝 $fwCount · 星辰 $xcCount)"
        $h2.Opacity = 0.7
        $h2.FontSize = 12
        $h2.VerticalAlignment = 'Center'
        $head.Children.Add($h2) | Out-Null
        
        $exp.Header = $head

        $inner = New-Object Windows.Controls.StackPanel
        $inner.Margin = [Windows.Thickness]::new(0, 4, 0, 8)
        foreach ($n in $items) { $inner.Children.Add((New-Row $n)) | Out-Null }
        $exp.Content = $inner
        $Groups.Children.Add($exp) | Out-Null
    }

    $stat = "聚合出口 $($script:Nodes.Count) 个 (蜂窝 + 星辰)　当前显示 $($list.Count) 个"
    if ($script:Lat.Count -gt 0) { $stat += "　已测速 $($script:Lat.Count) 个" }
    $CountText.Text = $stat
}

function Update-KernelUi {
    $run = Test-Kernel
    if ($run) {
        $Dot.Fill = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString('#5FD08A'))
        $KernelText.Text = '内核运行中 · 蜂窝 21001-21080 · 星辰 22001-22045 · 智能聚合 39999'
    } else {
        $Dot.Fill = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString('#E08A8A'))
        $KernelText.Text = '内核未运行 · 点「启动内核」'
    }
    if ($CockpitState) {
        $busy = [bool]$script:CoreAction
        $CockpitState.Text = if ($busy) { if ($script:CoreAction -eq 'start') { '正在启动' } else { '正在停止' } } elseif ($run) { '内核运行中' } else { '内核已停止' }
        $CockpitState.Foreground = if ($busy) { '#FFBA68' } elseif ($run) { '#B7FF00' } else { '#B9AFCA' }
        $BtnCoreToggle.Content = if ($busy) { '处理中…' } elseif ($run) { '停止内核' } else { '启动内核' }
        $BtnCoreToggle.IsEnabled = -not $busy
        $BtnStartCore.IsEnabled = (-not $busy -and -not $run)
        $BtnStopCore.IsEnabled = (-not $busy -and $run)
        $CockpitDetail.Text = if ($script:CoreActionError) { $script:CoreActionError } elseif ($run) { '本项目进程已确认 · 业务连通需探测 · 绑定保持不变' } else { '固定端口与账号绑定保持不变 · 关闭面板不停止内核' }
        $bindings = @(Get-BindingRows)
        $GoogleState.Text = if ($bindings.Count) { "$($bindings.Count) 个账号锚定 · 待验证" } else { '锚定状态未知' }
        $GoogleDetail.Text = '仅读取 Antigravity 固定绑定；未执行实时业务验证。'
        $candidates = @($script:Nodes | Where-Object { $_.claudeSupported -eq $true }).Count
        $ClaudeDetail.Text = "快照候选 $candidates 个 · 不代表当前使用出口或实时可用。"
    }
    return $run
}

# 异步刷新流水线：引擎子进程 + 测速收割均由定时器驱动，窗口全程可操作
$script:ReloadProc = $null
$script:ReloadProbe = $false
$script:ReloadTimer = New-Object Windows.Threading.DispatcherTimer
$script:ReloadTimer.Interval = [TimeSpan]::FromMilliseconds(800)
$script:ReloadTimer.Add_Tick({
    try {
        if ($script:ReloadProc -and -not $script:ReloadProc.HasExited) {
            $StatusText.Text = "$(if ($script:ReloadProbe) { '正在全量探测 125 个出口（约 1 分钟）' } else { '正在同步节点数据' })… 窗口可正常操作"
            return
        }
        $code = if ($script:ReloadProc) { $script:ReloadProc.ExitCode } else { 1 }
        $script:ReloadProc = $null
        $script:ReloadTimer.Stop()
        if ($code -ne 0) { $StatusText.Text = "同步失败（引擎退出码 $code），请查看 logs"; return }
        [void](Load-Nodes)
        Start-Latency
        $script:LatTimer.Stop()
        $script:LatTimer.Start()
    } catch {
        $script:ReloadTimer.Stop()
        $StatusText.Text = "刷新异常：$($_.Exception.Message)"
    }
})
$script:LatTimer = New-Object Windows.Threading.DispatcherTimer
$script:LatTimer.Interval = [TimeSpan]::FromMilliseconds(600)
$script:LatTimer.Add_Tick({
    try {
        if (-not $script:LatDone) {
            $pending = 0
            foreach ($t in $script:LatTasks) { if ($t -and -not $t.IsCompleted) { $pending++ } }
            $StatusText.Text = "正在并发测速（$($script:Nodes.Count) 个节点，剩余 $pending）…"
            return
        }
        $script:LatTimer.Stop()
        $script:ExpandedInit = $true
        Render
        $StatusText.Text = "数据更新于 $($script:DataStamp)　在线 $($script:AliveTotal) / $($script:Nodes.Count)　测速成功 $(if ($null -ne $script:LatOk) { $script:LatOk } else { 0 }) 个"
    } catch {
        $script:LatTimer.Stop()
        $StatusText.Text = "测速异常：$($_.Exception.Message)"
    }
})

function Full-Reload([switch]$Probe) {
    if ($script:ReloadProc -and -not $script:ReloadProc.HasExited) {
        $StatusText.Text = '上一轮刷新还在跑，请等它结束（状态栏有提示）'
        return $false
    }
    $StatusText.Text = if ($Probe) { '正在全量探测 125 个出口（约 1 分钟）… 窗口可正常操作' } else { '正在同步节点数据…' }
    Pump
    $extra = if ($Probe) { @() } else { @('-SkipProbe') }
    $script:ReloadProbe = [bool]$Probe
    $script:ReloadProc = Start-ScriptAsync 'gen-report.ps1' $extra
    $script:ReloadTimer.Stop()
    $script:ReloadTimer.Start()
    return $true
}

function Sync-FromHoneycomb {
    $StatusText.Text = '检测到蜂窝订阅已刷新，正在同步（重新生成配置 + 热重载内核）…'
    Pump
    $r = Invoke-Script 'gen-config.ps1'
    if ($r.Code -ne 0) { $StatusText.Text = "重新生成配置失败：$($r.Err.Trim())"; return }
    $cfg = Join-Path $Dir 'config.yaml'
    $secret = Get-Secret
    if ((Test-Kernel) -and $secret) {
        try {
            $body = @{ path = $cfg } | ConvertTo-Json -Compress
            [void](Invoke-WebRequest -Uri 'http://127.0.0.1:21909/configs?force=true' -Method Put `
                -Headers @{ Authorization = "Bearer $secret" } -Body $body -ContentType 'application/json' -TimeoutSec 25)
        } catch {
            $StatusText.Text = "热重载失败（将尝试重启内核）：$($_.Exception.Message)"
            Pump
            # Do not force-stop/restart from a failed hot reload; preserve operator control.
            $script:CoreActionError = '热重载失败，请在驾驶舱确认重启；现有内核未停止。'
            [void](Update-KernelUi)
            return
        }
    }
    [void](Full-Reload)
}

# ---------------- 巡检风控视图（原 pool-guard 控制台的能力，收进同一个面板） ----------------
$BtnViewExport   = $win.FindName('BtnViewExport')
$BtnViewGuard    = $win.FindName('BtnViewGuard')
$ViewExport      = $win.FindName('ViewExport')
$ViewGuard       = $win.FindName('ViewGuard')
$ViewHint        = $win.FindName('ViewHint')
$GSumTotal       = $win.FindName('GSumTotal')
$GSumAlive       = $win.FindName('GSumAlive')
$GSumDead        = $win.FindName('GSumDead')
$GSumPure        = $win.FindName('GSumPure')
$GSumBind        = $win.FindName('GSumBind')
$LvBind          = $win.FindName('LvBind')
$BtnGuardScan    = $win.FindName('BtnGuardScan')
$BtnGuardFill    = $win.FindName('BtnGuardFill')
$CmbGuardFilter  = $win.FindName('CmbGuardFilter')
$TxtGuardSearch  = $win.FindName('TxtGuardSearch')
$GuardCountText  = $win.FindName('GuardCountText')
$LvGuard         = $win.FindName('LvGuard')
$GuardBar        = $win.FindName('GuardBar')
$GuardStatusText = $win.FindName('GuardStatusText')
# XAML 里的 SelectedIndex 会在子项添加前生效，这里补一次，确保默认是「全部端口」
$CmbGuardFilter.SelectedIndex = 0

function New-GBrush([string]$hex) {
    $b = [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($hex))
    $b.Freeze()
    return $b
}
$GBrGreen  = New-GBrush '#5FD08A'
$GBrRed    = New-GBrush '#FF6B6B'
$GBrYellow = New-GBrush '#E8C46B'
$GBrGray   = New-GBrush '#7A7A85'
$GBrBlue   = New-GBrush '#7FB2FF'
$GBrPurple = New-GBrush '#C08CFF'
$GBrActive = New-GBrush '#2C3F63'
$GBrIdle   = New-GBrush '#26262C'

$script:GuardPorts     = @(21001..21080) + @(22001..22045)
$script:GuardMeta      = @{}
$script:GuardBind      = @()
$script:GuardBound     = @()
$script:GuardResults   = @{}
$script:GuardIndex     = @{}
$script:GuardRows      = @()
$script:GuardOc        = New-Object System.Collections.ObjectModel.ObservableCollection[object]
$script:GuardQueue     = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
$script:GuardScanning  = $false
$script:GuardScanStart = $null
$script:GuardScanPool  = $null
$script:GuardScanTasks = @()
$script:GuardInited    = $false
$script:GuardBindKey   = -1
$script:GuardFillPs    = $null
$script:GuardFillAsync = $null
$script:ActiveView     = 'Export'

function Set-GuardStatus([string]$msg) {
    $GuardStatusText.Text = $msg
    Write-PanelEvent 'guard' $msg
}

function Get-GuardMeta {
    $map = @{}
    $f = Get-RunFile 'nodes.json'
    if (Test-Path -LiteralPath $f) {
        try {
            foreach ($n in (Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json).nodes) { $map[[int]$n.port] = $n }
        } catch { }
    }
    return $map
}

function Get-BindingRows {
    $rows = New-Object System.Collections.ArrayList
    $cfgPath = 'C:\Users\1\.antigravity_tools\gui_config.json'
    if (-not (Test-Path -LiteralPath $cfgPath)) { return $rows }
    try { $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $rows }
    $idToPort = @{}; $idToName = @{}
    foreach ($px in $cfg.proxy.proxy_pool.proxies) {
        if ($px.url -match ':(\d+)') { $idToPort[$px.id] = [int]$Matches[1]; $idToName[$px.id] = $px.name }
    }
    $emailById = @{}
    $accPath = 'C:\Users\1\.antigravity_tools\accounts.json'
    if (Test-Path -LiteralPath $accPath) {
        try {
            foreach ($a in (Get-Content -LiteralPath $accPath -Raw -Encoding UTF8 | ConvertFrom-Json).accounts) { $emailById[$a.id] = $a.email }
        } catch { }
    }
    foreach ($prop in $cfg.proxy.proxy_pool.account_bindings.PSObject.Properties) {
        $accId = $prop.Name
        $pxId = [string]$prop.Value
        $short = if ($accId.Length -ge 8) { $accId.Substring(0, 8) } else { $accId }
        [void]$rows.Add([PSCustomObject]@{
            Email     = if ($emailById.ContainsKey($accId)) { $emailById[$accId] } else { "未登记账号 $short" }
            ProxyName = if ($idToName.ContainsKey($pxId)) { $idToName[$pxId] } else { '(代理条目缺失)' }
            Port      = if ($idToPort.ContainsKey($pxId)) { $idToPort[$pxId] } else { 0 }
        })
    }
    return $rows
}

function New-GuardRow([int]$Port, $probe) {
    $meta = $script:GuardMeta[$Port]
    $brand = if ($Port -lt 22000) { '蜂窝' } else { '星辰' }
    $country = if ($meta -and $meta.country) { $meta.country } else { '—' }
    $gcc = if ($meta -and $meta.googleCountry) { $meta.googleCountry } else { '—' }
    $name = if ($meta -and $meta.orig) { $meta.orig } else { '(未登记节点)' }
    if ($probe) {
        if ($probe.CfOk -and $probe.GoogleOk) { $status = '健康 · 双通'; $sbr = $GBrGreen }
        elseif ($probe.CfOk)                  { $status = 'Google 不通'; $sbr = $GBrYellow }
        elseif ($probe.GoogleOk)              { $status = 'Cloudflare 不通'; $sbr = $GBrYellow }
        else                                  { $status = '不通'; $sbr = $GBrRed }
        $exitIp = if ($probe.ExitIp) { $probe.ExitIp } else { '—' }
    } else {
        $status = '探测中…'; $sbr = $GBrGray; $exitIp = '…'
    }
    $isCn = ($gcc -eq 'China' -or $gcc -eq 'Hong Kong' -or $gcc -eq 'Macao')
    $isPure = [bool]($meta -and $meta.antigravitySupported -and -not $isCn)
    if ($isCn)       { $risk = '送中 · 剔除'; $rbr = $GBrRed }
    elseif ($isPure) { $risk = 'Gemini 纯净'; $rbr = $GBrGreen }
    else             { $risk = '观望'; $rbr = $GBrGray }
    return [PSCustomObject]@{
        Port        = $Port
        Brand       = $brand
        BrandBrush  = if ($Port -lt 22000) { $GBrBlue } else { $GBrPurple }
        Name        = $name
        Country     = $country
        Risk        = $risk
        RiskBrush   = $rbr
        Status      = $status
        StatusBrush = $sbr
        ExitIp      = $exitIp
        Alive       = [bool]($probe -and $probe.CfOk -and $probe.GoogleOk)
        Probed      = [bool]$probe
        IsBound     = [bool]($script:GuardBound -contains $Port)
        IsPure      = $isPure
    }
}

function Initialize-Guard {
    $script:GuardMeta  = Get-GuardMeta
    $script:GuardBind  = @(Get-BindingRows)
    $script:GuardBound = @($script:GuardBind | Where-Object { $_.Port -gt 0 } | Select-Object -ExpandProperty Port -Unique)
    $script:GuardOc.Clear()
    $script:GuardIndex = @{}
    $i = 0
    foreach ($p in $script:GuardPorts) {
        $script:GuardOc.Add((New-GuardRow $p $null))
        $script:GuardIndex[$p] = $i
        $i++
    }
    $script:GuardRows = @($script:GuardOc)
    $script:GuardBindKey = -1
    $LvGuard.ItemsSource = $script:GuardOc
    $GuardCountText.Text = "显示 $($script:GuardRows.Count) / $($script:GuardRows.Count)"
    $null = Refresh-GuardSummary
    Refresh-GuardBindings
}

function Apply-GuardFilter {
    if ($script:GuardScanning) { return }
    $mode = ''
    try { $mode = [string]$CmbGuardFilter.SelectedItem.Content } catch { }
    $q = $TxtGuardSearch.Text.Trim().ToLower()
    $list = New-Object System.Collections.ArrayList
    foreach ($r in $script:GuardRows) {
        $skip = $false
        switch ($mode) {
            '仅存活'             { if (-not $r.Alive) { $skip = $true } }
            '仅不通'             { if ($r.Alive -or -not $r.Probed) { $skip = $true } }
            '仅 Gemini 纯净可用'  { if (-not $r.IsPure) { $skip = $true } }
            '仅账号绑定'          { if (-not $r.IsBound) { $skip = $true } }
            '仅备选池'            { if ($r.IsBound) { $skip = $true } }
        }
        if ($skip) { continue }
        if ($q) {
            $hay = ("$($r.Port) $($r.Name) $($r.Country) $($r.Brand)").ToLower()
            if (-not $hay.Contains($q)) { continue }
        }
        [void]$list.Add($r)
    }
    $LvGuard.ItemsSource = $list
    $GuardCountText.Text = "显示 $($list.Count) / $($script:GuardRows.Count)"
}

function Refresh-GuardSummary {
    $probed = @($script:GuardRows | Where-Object { $_.Probed })
    $alive  = @($probed | Where-Object { $_.Alive })
    $dead   = @($probed | Where-Object { -not $_.Alive })
    $pure   = @($alive | Where-Object { $_.IsPure })
    $GSumTotal.Text = "$($script:GuardRows.Count)"
    $GSumAlive.Text = if ($probed.Count) { "$($alive.Count)" } else { '—' }
    $GSumDead.Text  = if ($probed.Count) { "$($dead.Count)" } else { '—' }
    $GSumPure.Text  = if ($probed.Count) { "$($pure.Count)" } else { '—' }
    $bindAlive = 0
    foreach ($b in $script:GuardBind) {
        $r = $script:GuardRows | Where-Object { $_.Port -eq $b.Port } | Select-Object -First 1
        if ($r -and $r.Alive) { $bindAlive++ }
    }
    $total = $script:GuardBind.Count
    if (-not $probed.Count) {
        $GSumBind.Text = "$total 个"
        $GSumBind.Foreground = $GBrGray
    } else {
        $GSumBind.Text = "$bindAlive / $total"
        $GSumBind.Foreground = if ($bindAlive -eq $total) { $GBrGreen } else { $GBrRed }
    }
    return @{ Alive = $alive.Count; Dead = $dead.Count; Probed = $probed.Count; Pure = $pure.Count; BindAlive = $bindAlive; BindTotal = $total }
}

function Refresh-GuardBindings {
    # 先对绑定端口做一发并行实时 TCP 探活（本地回环，1 秒内完成），
    # 让状态列在没有跑巡检时也能即时给出结论，不再显示「待探测」。
    $tcpMap = @{}
    $tcpTasks = @{}
    foreach ($b in $script:GuardBind) {
        if ($b.Port -gt 0 -and -not $tcpTasks.ContainsKey($b.Port)) {
            try {
                $c = New-Object Net.Sockets.TcpClient
                $tcpTasks[$b.Port] = @{ C = $c; T = $c.ConnectAsync('127.0.0.1', $b.Port) }
            } catch { }
        }
    }
    Start-Sleep -Milliseconds 900
    foreach ($p in $tcpTasks.Keys) {
        $t = $tcpTasks[$p]
        $tcpMap[$p] = ($t.T.IsCompleted -and $t.C.Connected)
        try { $t.C.Close() } catch { }
    }

    # 当场测速：对 7 个绑定端口并行调内核延迟 API（本地回环，约 3 秒封顶）
    $latMap = @{}
    $secret = Get-Secret
    if ($secret) {
        $lc = New-Object System.Net.Http.HttpClient
        $lc.Timeout = [TimeSpan]::FromSeconds(4)
        $lc.DefaultRequestHeaders.Add('Authorization', "Bearer $secret")
        $ltasks = @{}
        foreach ($b in $script:GuardBind) {
            $meta0 = $script:GuardMeta[$b.Port]
            if ($b.Port -gt 0 -and $meta0 -and $meta0.name -and -not $ltasks.ContainsKey($b.Port)) {
                $u = "http://127.0.0.1:21909/proxies/$($meta0.name)/delay?timeout=3000&url=http%3A%2F%2Fwww.gstatic.com%2Fgenerate_204"
                try { $ltasks[$b.Port] = $lc.GetStringAsync($u) } catch { }
            }
        }
        try {
            [System.Threading.Tasks.Task]::WaitAll(@($ltasks.Values | Where-Object { $_ }), 3500) | Out-Null
        } catch { }
        foreach ($p in $ltasks.Keys) {
            $tk = $ltasks[$p]
            if ($tk -and $tk.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) {
                try { $latMap[$p] = ($tk.Result | ConvertFrom-Json).delay } catch { }
            }
        }
        $lc.Dispose()
    }

    $rows = New-Object System.Collections.ArrayList
    foreach ($b in $script:GuardBind) {
        $r = $script:GuardRows | Where-Object { $_.Port -eq $b.Port } | Select-Object -First 1
        $meta = $script:GuardMeta[$b.Port]
        $lat = $latMap[$b.Port]
        if ($r -and $r.Probed) {
            if ($r.Alive) { $status = if ($lat) { "锚定正常 · ${lat}ms" } else { '锚定正常 · HEALTHY' }; $sbr = $GBrGreen }
            else          { $status = '确认故障 · CRITICAL'; $sbr = $GBrRed }
        } elseif ($tcpMap[$b.Port]) {
            if ($meta -and $meta.ip) {
                $loc = if ($meta.country) { $meta.country } else { $meta.googleCountry }
                $status = if ($lat) { "体检正常 · $loc · ${lat}ms" } else { "体检正常 · $loc" }; $sbr = $GBrGreen
            } else {
                $status = if ($lat) { "端口在线 · ${lat}ms" } else { '端口在线 · 体检数据待更新' }; $sbr = $GBrBlue
            }
        } else {
            $status = '出口不通 · 需排查'; $sbr = $GBrRed
        }
        [void]$rows.Add([PSCustomObject]@{
            Email       = $b.Email
            PortText    = if ($b.Port) { "$($b.Port)" } else { '—' }
            ProxyName   = $b.ProxyName
            Status      = $status
            StatusBrush = $sbr
        })
    }
    $LvBind.ItemsSource = $rows
}

function Start-GuardScan {
    $script:GuardQueue.Clear()
    $script:GuardScanning = $true
    $script:GuardScanStart = Get-Date
    $pool = [RunspaceFactory]::CreateRunspacePool(1, 24)
    $pool.Open()
    $script:GuardScanPool = $pool
    $script:GuardScanTasks = @()
    $sink = $script:GuardQueue
    foreach ($p in $script:GuardPorts) {
        $ps = [PowerShell]::Create()
        $ps.RunspacePool = $pool
        $null = $ps.AddScript({
            param($port, $sink)
            $ip = (& curl.exe -s --max-time 6 --socks5-hostname "127.0.0.1:$port" https://api.ipify.org 2>$null)
            $cf = (& curl.exe -s -o NUL --max-time 6 -w "%{http_code}" --socks5-hostname "127.0.0.1:$port" https://cp.cloudflare.com/generate_204 2>$null)
            $gg = (& curl.exe -s -o NUL --max-time 6 -w "%{http_code}" --socks5-hostname "127.0.0.1:$port" https://www.google.com/generate_204 2>$null)
            [void]$sink.Add([PSCustomObject]@{
                Port     = [int]$port
                ExitIp   = if ($ip) { "$ip".Trim() } else { '' }
                CfOk     = ("$cf" -eq '204')
                GoogleOk = ("$gg" -eq '204')
            })
        }).AddArgument($p).AddArgument($sink)
        $script:GuardScanTasks += [PSCustomObject]@{ PS = $ps; Async = $ps.BeginInvoke() }
    }
}

function Stop-GuardScan {
    foreach ($h in $script:GuardScanTasks) {
        try { [void]$h.PS.EndInvoke($h.Async) } catch { }
        try { $h.PS.Dispose() } catch { }
    }
    $script:GuardScanTasks = @()
    if ($script:GuardScanPool) {
        try { $script:GuardScanPool.Close(); $script:GuardScanPool.Dispose() } catch { }
        $script:GuardScanPool = $null
    }
    $script:GuardScanning = $false
}

function Switch-View([string]$v) {
    Set-PanelMode $true
    $isGuard = ($v -eq 'Guard')
    $script:ActiveView = if ($isGuard) { 'Guard' } else { 'Export' }
    $ViewGuard.Visibility  = if ($isGuard) { 'Visible' } else { 'Collapsed' }
    $ViewExport.Visibility = if ($isGuard) { 'Collapsed' } else { 'Visible' }
    $BtnViewGuard.Background  = if ($isGuard) { $GBrActive } else { $GBrIdle }
    $BtnViewExport.Background = if ($isGuard) { $GBrIdle } else { $GBrActive }
    $ViewHint.Text = if ($isGuard) {
        '体检全网出口、核对账号粘性锚定；写回由 pool-guard.ps1 安全执行'
    } else {
        '取用出口配置；或对全网 125 个出口做体检、看账号粘性锚定与风控状态'
    }
    if ($isGuard) {
        if (-not (Test-Kernel)) {
            Set-GuardStatus '⚠️ 内核未运行：所有出口都连不上。先切回「出口取用」点「启动内核」。'
            return
        }
        if (-not $script:GuardInited) {
            $script:GuardInited = $true
            Initialize-Guard
        }
        if (-not $script:GuardScanning -and $script:GuardResults.Count -eq 0) {
            Set-GuardStatus '就绪。点「开始全网巡检」实测 125 个出口（约 25 秒）。'
        }
    }
}

$BtnViewExport.Add_Click({ Switch-View 'Export' })
$BtnViewGuard.Add_Click({ Switch-View 'Guard' })

$BtnGuardScan.Add_Click({
    if ($script:GuardScanning) { Set-GuardStatus '巡检正在进行中…'; return }
    if (-not (Test-Kernel)) { Set-GuardStatus '⚠️ 内核未运行，无法巡检。请先切回「出口取用」点「启动内核」。'; return }
    Set-GuardStatus '正在并发巡检 125 个端口…'
    $script:GuardResults = @{}
    $script:GuardInited = $true
    Initialize-Guard
    $GuardBar.Value = 0
    Start-GuardScan
    $script:GuardTimer.Start()
})

$BtnGuardFill.Add_Click({
    if ($script:GuardScanning) { Set-GuardStatus '请等本轮巡检结束后再充盈备选池。'; return }
    if ($script:GuardFillAsync) { Set-GuardStatus '充盈任务正在进行中…'; return }
    $guardScript = Join-Path $Dir 'pool-guard.ps1'
    if (-not (Test-Path -LiteralPath $guardScript)) { Set-GuardStatus "找不到 pool-guard.ps1：$guardScript"; return }
    $BtnGuardFill.IsEnabled = $false
    Set-GuardStatus '正在后台充盈备选池（全量实测并安全回写 gui_config.json，约 1 分钟，界面可继续使用）…'
    $script:GuardFillPs = [PowerShell]::Create()
    $null = $script:GuardFillPs.AddScript({
        param($sp)
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $sp -Mode RefreshStandby 2>&1
    }).AddArgument($guardScript)
    $script:GuardFillAsync = $script:GuardFillPs.BeginInvoke()
})

$CmbGuardFilter.Add_SelectionChanged({ Apply-GuardFilter })
$TxtGuardSearch.Add_TextChanged({ Apply-GuardFilter })

$script:GuardTimer = New-Object Windows.Threading.DispatcherTimer
$script:GuardTimer.Interval = [TimeSpan]::FromMilliseconds(400)
$script:GuardTimer.Add_Tick({
    if ($script:ActiveView -ne 'Guard' -and -not $script:GuardScanning -and -not $script:GuardFillAsync) { return }

    $absorbed = 0
    while ($script:GuardQueue.Count -gt 0 -and $absorbed -lt 40) {
        $item = $script:GuardQueue[0]
        $script:GuardQueue.RemoveAt(0)
        $absorbed++
        if (-not $item) { continue }
        $script:GuardResults[$item.Port] = $item
        $idx = $script:GuardIndex[$item.Port]
        if ($null -ne $idx) {
            $row = New-GuardRow $item.Port $item
            $script:GuardOc[$idx] = $row
            $script:GuardRows[$idx] = $row
        }
    }

    $done = $script:GuardResults.Count
    $GuardBar.Value = [Math]::Min($done, 125)
    if ($script:GuardScanning) {
        $aliveNow = @($script:GuardResults.Values | Where-Object { $_.CfOk -and $_.GoogleOk }).Count
        $GuardStatusText.Text = "正在并发巡检 125 个端口… 已完成 $done / 125 · 双通 $aliveNow"
    }

    $s = Refresh-GuardSummary
    $key = ($s.Probed * 100) + $s.BindAlive
    if ($key -ne $script:GuardBindKey) {
        $script:GuardBindKey = $key
        Refresh-GuardBindings
    }

    if ($script:GuardScanning -and $done -ge 125) {
        Stop-GuardScan
        $used = [Math]::Round(((Get-Date) - $script:GuardScanStart).TotalSeconds, 1)
        Apply-GuardFilter
        $msg = "巡检完成：双通存活 $($s.Alive) / 125，不通 $($s.Dead)，Gemini 纯净 $($s.Pure)，账号绑定健康 $($s.BindAlive)/$($s.BindTotal)，用时 ${used}s。"
        if ($s.BindAlive -lt $s.BindTotal) { $msg += ' ⚠️ 有账号绑定节点故障：非确凿物理故障不要换绑，先复测确认。' }
        Set-GuardStatus $msg
    }

    if ($script:GuardFillAsync -and $script:GuardFillAsync.IsCompleted) {
        try {
            $out = $script:GuardFillPs.EndInvoke($script:GuardFillAsync)
            $hit = @($out | ForEach-Object { "$_" } | Where-Object { $_ -match '写入自检通过|充盈至|纯净清单|数量异常|BOM' })
            $tail = if ($hit.Count) { ($hit | Select-Object -Last 2) -join ' ｜ ' } else { '已完成' }
            Set-GuardStatus "备选池充盈结束：$tail"
        } catch {
            Set-GuardStatus "备选池充盈失败：$_"
        } finally {
            try { $script:GuardFillPs.Dispose() } catch { }
            $script:GuardFillPs = $null
            $script:GuardFillAsync = $null
            $BtnGuardFill.IsEnabled = $true
        }
    }
})
$script:GuardTimer.Start()

# ---------------- 事件绑定 ----------------
# ---------------- EVA 驾驶舱主控：启动/停止 ----------------
function Start-OwnedCore {
    if ($script:CoreAction -or (Test-Kernel)) { return }
    $script:CoreActionError = ''
    try {
        $exe = Join-Path $Dir 'bin\mihomo.exe'
        if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $Dir 'mihomo.exe' }
        $cfg = Get-RunFile 'config.yaml'
        if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $cfg)) { throw '缺少本项目内核或配置，未启动。' }
        # Direct owned executable launch avoids the legacy launcher global-name check.
        $script:CoreLaunchProc = Start-Process -FilePath $exe -ArgumentList @('-d', "`"$Dir`"", '-f', "`"$cfg`"") -WorkingDirectory $Dir -WindowStyle Hidden -PassThru
        $script:CoreAction = 'start'
        $script:CoreActionStarted = Get-Date
        $script:CoreControlTimer.Start()
    } catch { $script:CoreActionError = "启动失败：$($_.Exception.Message)" }
    [void](Update-KernelUi)
}
function Stop-OwnedCore {
    if ($script:CoreAction) { return }
    $owned = @(Get-OwnedCoreProcesses)
    if (-not $owned.Count) { [void](Update-KernelUi); return }
    $confirm = [Windows.MessageBox]::Show('仅停止本项目路径的内核；21001-21080、22001-22045、39999 消费者会断网。其他 mihomo 不受影响。继续？', '停止本项目内核', 'YesNo', 'Warning')
    if ($confirm -ne 'Yes') { return }
    $script:CoreActionError = ''
    try {
        foreach ($p in $owned) {
            # Recheck path immediately before killing the process object (not a bare recycled PID).
            if (@((Join-Path $Dir 'bin\mihomo.exe'), (Join-Path $Dir 'mihomo.exe')) -contains $p.Path) { $p.Kill() }
        }
        $script:CoreAction = 'stop'
        $script:CoreActionStarted = Get-Date
        $script:CoreControlTimer.Start()
    } catch { $script:CoreActionError = "停止失败：$($_.Exception.Message)" }
    [void](Update-KernelUi)
}
$script:CoreControlTimer = New-Object Windows.Threading.DispatcherTimer
$script:CoreControlTimer.Interval = [TimeSpan]::FromMilliseconds(400)
$script:CoreControlTimer.Add_Tick({
    try {
        $run = Test-Kernel
        $elapsed = ((Get-Date) - $script:CoreActionStarted).TotalSeconds
        $finished = if ($script:CoreAction -eq 'start') { ($elapsed -ge 2 -and $run) -or ($script:CoreLaunchProc -and $script:CoreLaunchProc.HasExited) } else { -not $run }
        if ($finished -or $elapsed -ge 12) {
            if (($script:CoreAction -eq 'start' -and -not $run) -or ($script:CoreAction -eq 'stop' -and $run)) { $script:CoreActionError = '操作未确认成功，请查看调试日志；未触碰其他内核。' }
            $script:CoreAction = $null
            $script:CoreControlTimer.Stop()
            $script:Lat = @{}
            if ($script:CoreLaunchProc) { $script:CoreLaunchProc.Dispose(); $script:CoreLaunchProc = $null }
        }
        [void](Update-KernelUi)
    } catch { $script:CoreActionError = $_.Exception.Message; $script:CoreAction = $null; $script:CoreControlTimer.Stop(); [void](Update-KernelUi) }
})
$BtnStartCore.Add_Click({ Start-OwnedCore })
$BtnStopCore.Add_Click({ Stop-OwnedCore })
$BtnCoreToggle.Add_Click({ if (Test-Kernel) { Stop-OwnedCore } else { Start-OwnedCore } })

# ---------------- 常态情报与工程师指令（只改显示规则，不改端口绑定）
$script:CockpitUiTimer = New-Object Windows.Threading.DispatcherTimer
$script:CockpitUiTimer.Interval = [TimeSpan]::FromSeconds(1)
$script:CockpitUiTimer.Add_Tick({
    if ($CockpitClock) { $CockpitClock.Text = (Get-Date -Format 'HH:mm:ss') }
    Import-GatewayDigest
    if ($FlowState -and (Test-Kernel)) {
        $FlowState.Text = '网关在线'
        $FlowDetail.Text = '本地内核已确认 · 业务日志待接入'
    }
})
$script:CockpitUiTimer.Start()
Add-CockpitMessage 'SYSTEM' '驾驶舱已上线：正在等待网关摘要' 'normal'
$BtnEngineerApply.Add_Click({ Apply-EngineerDirective $EngineerInput.Text; $EngineerInput.Clear() })
$EngineerInput.Add_KeyDown({ param($sender, $e); if ($e.Key -eq 'Enter' -and ([Windows.Input.Keyboard]::Modifiers -band [Windows.Input.ModifierKeys]::Control)) { Apply-EngineerDirective $EngineerInput.Text; $EngineerInput.Clear(); $e.Handled = $true } })
$BtnGlmDigest.Add_Click({ $EngineerStatus.Text = 'ENGINEER // GLM 常态汇报接口已预留，当前使用本地可读摘要'; Add-CockpitMessage 'GLM' '常态汇报接口已预留，尚未向外部模型发送日志' 'warn' })

# ---------------- 主按钮：体检一次（唯一的日常操作按钮）----------------
$BtnHealth.Add_Click({
    if ($script:ActiveView -eq 'Guard') {
        if (-not $script:GuardScanning) { Start-GuardScan }
        $StatusText.Text = '🩺 全网体检已开始（约 25 秒），下方表格实时更新'
    } else {
        [void](Full-Reload -Probe)
        $StatusText.Text = '🩺 正在全量体检 125 个出口（约 1 分钟，后台进行，窗口可正常操作）'
    }
})

# ---------------- 维护菜单（冷门操作全部收编于此）----------------
$script:MaintMenu = New-Object Windows.Forms.ContextMenuStrip
$miStart = $script:MaintMenu.Items.Add('▶ 启动内核')
$miStart.Add_Click({ Start-OwnedCore })
$miStop = $script:MaintMenu.Items.Add('■ 停止内核（浏览器环境会断代理）')
$miStop.Add_Click({ Stop-OwnedCore })
[void]$script:MaintMenu.Items.Add('-')
$miSpeed = $script:MaintMenu.Items.Add('⏱ 仅重新测速（不重新体检）')
$miSpeed.Add_Click({
    if (-not $script:Nodes.Count) { $StatusText.Text = '请先「体检一次」加载数据'; return }
    Start-Latency
    $script:LatTimer.Stop()
    $script:LatTimer.Start()
    $StatusText.Text = '⏱ 正在并发测速（后台进行，窗口可正常操作）…'
})
[void]$script:MaintMenu.Items.Add('-')
$miP1 = $script:MaintMenu.Items.Add('📋 复制全部端口（P1 智能解析格式）')
$miP1.Add_Click({ Invoke-BatchExport 'IP:端口' 'P1 智能解析格式' })
$miSocks = $script:MaintMenu.Items.Add('📋 复制全部 SOCKS5')
$miSocks.Add_Click({ Invoke-BatchExport 'socks5://' 'SOCKS5' })
$miHttp = $script:MaintMenu.Items.Add('📋 复制全部 HTTP')
$miHttp.Add_Click({ Invoke-BatchExport 'http://' 'HTTP' })
$BtnMaintain.Add_Click({
    $script:MaintMenu.Show([Windows.Forms.Cursor]::Position)
})

# ---- 场景靶场（scenes.json 驱动，缺省回退内置四场景）----
$script:Scenes = @()
$scenesFile = Get-RunFile 'scenes.json'
if (Test-Path -LiteralPath $scenesFile) {
    try { $script:Scenes = Get-Content -LiteralPath $scenesFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}
if (-not $script:Scenes -or $script:Scenes.Count -eq 0) {
    $script:Scenes = @(
        [pscustomobject]@{ id='antigravity'; name='✨ 反重力 / Gemini (Google原生)'; chipBg='#1B432C'; matchKey='antigravitySupported' },
        [pscustomobject]@{ id='claude'; name='🟣 Claude 专属 (Anthropic直连)'; chipBg='#3B1E4A'; matchKey='claudeSupported' },
        [pscustomobject]@{ id='openai'; name='🟢 ChatGPT / OpenAI (API高速)'; chipBg='#1A3A2A'; matchKey='openaiSupported' },
        [pscustomobject]@{ id='facebook'; name='🔵 Facebook / 海外社媒 (住宅纯净)'; chipBg='#1E2E4A'; matchKey='facebookSupported' }
    )
}
foreach ($s in $script:Scenes) { [void]$CmbScene.Items.Add($s.name) }
if ($CmbScene.Items.Count -gt 0) { $CmbScene.SelectedIndex = 0 }

function Update-SceneButton {
    if (-not $CmbScene -or -not $BtnCopyScenePool) { return }
    $idx = $CmbScene.SelectedIndex
    if ($idx -lt 0 -or $idx -ge $script:Scenes.Count) { return }
    $s = $script:Scenes[$idx]
    $matchedCount = 0
    if ($script:Nodes) {
        $key = if ($s.matchKey) { $s.matchKey } else { "$($s.id)Supported" }
        $matchedCount = @($script:Nodes | Where-Object { $_.$key -eq $true }).Count
    }
    $BtnCopyScenePool.Content = "⚡ 复制场景池 ($matchedCount)"
    if ($s.chipBg) {
        try { $BtnCopyScenePool.Background = (New-Object Windows.Media.BrushConverter).ConvertFromString($s.chipBg) } catch { }
    }
}
$CmbScene.Add_SelectionChanged({ Update-SceneButton })

$BtnCopyScenePool.Add_Click({
        $idx = $CmbScene.SelectedIndex
        if ($idx -lt 0 -or $idx -ge $script:Scenes.Count) { return }
        $s = $script:Scenes[$idx]
        $key = if ($s.matchKey) { $s.matchKey } else { "$($s.id)Supported" }
        $pool = @($script:Nodes | Where-Object { $_.$key -eq $true } | Sort-Object healthScore -Descending)
        if ($pool.Count -eq 0) {
            $StatusText.Text = "当前未发现适用于「$($s.name)」的节点，请先刷新数据。"
            return
        }
        $fmt = $CmbFormat.SelectedItem
        if ($fmt -eq 'JSON 数组 (全字段无损)') {
            $list = foreach ($item in $pool) {
                $name = Get-NodeCleanName $item
                [ordered]@{
                    url = "socks5h://$($script:ListenAddr):$($item.port)"
                    name = $name
                    tags = @($s.id)
                    priority = 1
                    is_healthy = $true
                    country = $item.country
                    googleCountry = $item.googleCountry
                    port = $item.port
                }
            }
            $copyText = $list | ConvertTo-Json -Depth 3
        } else {
            $lines = foreach ($item in $pool) { Format-ProxyEntry $item $fmt }
            $copyText = $lines -join "`r`n"
        }
        try { [Windows.Clipboard]::SetText($copyText) } catch { }
        $StatusText.Text = "⚡ 已复制 $($pool.Count) 个「$($s.name)」场景节点至剪贴板（格式: $fmt）"
        $this.Content = "已复制 $($pool.Count) 个节点"
        $t = New-Object Windows.Threading.DispatcherTimer
        $t.Interval = [TimeSpan]::FromSeconds(2)
        $t.Tag = $this
        $t.Add_Tick({
            param($sender, $args)
            $sender.Stop()
            Update-SceneButton
        })
        $t.Start()
    })

# ---- 批量导出（维护菜单调用）----
function Invoke-BatchExport([string]$fmt, [string]$label) {
    if (-not $script:Nodes.Count) { $StatusText.Text = '请先「体检一次」加载数据'; return }
    $lines = foreach ($n in $script:Nodes) { Format-ProxyEntry $n $fmt }
    try { [Windows.Clipboard]::SetText(($lines -join "`r`n")) } catch { }
    $StatusText.Text = "📋 已复制全量 $($script:Nodes.Count) 个端口（$label）"
}

if ($BtnCopyPhoneProxy) {
    $BtnCopyPhoneProxy.Add_Click({
        try { [Windows.Clipboard]::SetText('192.168.0.107:39999') } catch { }
        $this.Content = '已复制'
        $script:StatusText.Text = '已复制手机/局域网智能分流代理地址：192.168.0.107:39999'
        $t = New-Object Windows.Threading.DispatcherTimer
        $t.Interval = [TimeSpan]::FromSeconds(1.5)
        $t.Tag = $this
        $t.Add_Tick({
            param($sender, $args)
            $sender.Tag.Content = '复制代理地址'
            $sender.Stop()
        })
        $t.Start()
    })
}

if ($BtnPhoneCmd) {
    $BtnPhoneCmd.Add_Click({
        $cmd = 'settings put global http_proxy 192.168.0.107:39999'
        try { [Windows.Clipboard]::SetText($cmd) } catch { }
        $this.Content = '已复制命令'
        $script:StatusText.Text = "已复制手机挂载命令（无需装App，Root下执行生效）：$cmd"
        $t = New-Object Windows.Threading.DispatcherTimer
        $t.Interval = [TimeSpan]::FromSeconds(1.5)
        $t.Tag = $this
        $t.Add_Tick({
            param($sender, $args)
            $sender.Tag.Content = '挂载命令'
            $sender.Stop()
        })
        $t.Start()
    })
}


$BtnExpand.Add_Click({ foreach ($e in $Groups.Children) { $e.IsExpanded = $true } })
$BtnCollapse.Add_Click({ foreach ($e in $Groups.Children) { $e.IsExpanded = $false } })
$CmbFilter.Add_SelectionChanged({ Render })
$CmbFormat.Add_SelectionChanged({
    $fmt = $CmbFormat.SelectedItem
    $StatusText.Text = "复制格式已切换为 $fmt（点任意行的「复制」按钮）"
})
$TxtSearch.Add_GotFocus({ if ($TxtSearch.Text -eq '搜索地区 / 城市 / 端口 / IP') { $TxtSearch.Text = '' } })
$TxtSearch.Add_TextChanged({ if ($script:Nodes.Count) { Render } })

# 自动同步：每 12 秒检查蜂窝订阅 profile 是否被刷新
$script:Timer = New-Object Windows.Threading.DispatcherTimer
$script:Timer.Interval = [TimeSpan]::FromSeconds(12)
$script:Timer.Add_Tick({
    try {
        $info = Get-ProfileInfo
        if ($info -and $info.Write) {
            if ($script:LastWrite -and $info.Write -ne $script:LastWrite) {
                $script:LastWrite = $info.Write
                Sync-FromHoneycomb
            } elseif (-not $script:LastWrite) {
                $script:LastWrite = $info.Write
            }
        }
        [void](Update-KernelUi)
    } catch {
        Write-PanelEvent 'sync-error' $_.Exception.Message
        $StatusText.Text = '自动同步遇到问题，请查看 logs\panel.log；代理内核独立运行。'
    }
})
$script:Timer.Start()

# ---------------- 启动 ----------------
$script:ListenAddr = '127.0.0.1'
try {
    $info = Get-ProfileInfo
    if ($info) {
        $script:ProfilePath = $info.Path
        $script:LastWrite = $info.Write
        $StatusText.Text = "订阅来源：$($info.Path)"
    }
    [void](Update-KernelUi)
    if (Load-Nodes) {
        Render
        if (Test-Kernel) {
            Start-Latency
            $script:LatTimer.Stop()
            $script:LatTimer.Start()
        } else {
            $StatusText.Text = "数据更新于 $($script:DataStamp)　内核未运行，延迟未测（点「启动内核」后会自动测速）"
        }
    } else {
        $StatusText.Text = '还没有 nodes.json，请点「刷新数据」生成。'
    }
} catch {
    Write-PanelEvent 'startup-error' ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message)
    $StatusText.Text = '数据加载遇到问题，面板仍可操作；详情见 logs\panel.log。'
}

if ($View -eq 'Guard') { Switch-View 'Guard' }

try {
    $app = New-Object Windows.Application
    $app.ShutdownMode = [Windows.ShutdownMode]::OnMainWindowClose
    $app.Add_DispatcherUnhandledException({
        param($sender, $e)
        Write-PanelEvent 'ui-error' ($e.Exception.GetType().FullName + ': ' + $e.Exception.Message)
        $StatusText.Text = '面板操作遇到问题，详情见 logs\panel.log；代理内核保持运行。'
        $e.Handled = $true
    })
    [void]$app.Run($win)
} finally {
    $script:Timer.Stop()
    $script:CoreControlTimer.Stop()
    $script:ReloadTimer.Stop()
    $script:LatTimer.Stop()
    if ($script:CoreLaunchProc) { $script:CoreLaunchProc.Dispose() }
    $script:ShowTimer.Stop()
    $script:GuardTimer.Stop()
    if ($script:CockpitUiTimer) { $script:CockpitUiTimer.Stop() }
    if ($script:GuardScanning) { Stop-GuardScan }
    $script:Tray.Visible = $false
    $script:Tray.Dispose()
    $trayMenu.Dispose()
    $script:ShowSignal.Dispose()
    $script:GuardSignal.Dispose()
    Write-PanelEvent 'stopped' $(if ($script:ExitRequested) { 'exit-menu' } else { 'unexpected-or-system' })
    $script:mutex.ReleaseMutex()
    $script:mutex.Dispose()
}
