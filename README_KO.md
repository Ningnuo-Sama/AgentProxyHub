<div align="center">

<img src="https://raw.githubusercontent.com/ningnuo-dot/AgentProxyHub/main/assets/icon.png" width="128" height="128" alt="AgentProxyHub Logo" />

# AgentProxyHub

**AI 에이전트, 안티디텍트 브라우저 및 다중 계정 매트릭스를 위한 지능형 프록시 허브**

[![GitHub Release](https://img.shields.io/github/v/release/ningnuo-dot/AgentProxyHub?style=flat-square&color=blue)](https://github.com/ningnuo-dot/AgentProxyHub/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-slate.svg?style=flat-square)](README_KO.md)
[![MCP Ready](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple.svg?style=flat-square)](mcp/server.py)

[中文说明](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)

</div>

---

### 💡 왜 AgentProxyHub인가요?

해외 다중 계정 운영, 지문 격리 브라우저(P1, CloakMulti, AdsPower 등) 사용, 혹은 Claude Code 및 자동화 크롤러 실행 시 기존 프록시 클라이언트는 명확한 한계를 보입니다:

1. **단일 출구 및 계정 연쇄 정지 위험**: 일반 프록시 클라이언트는 단일 포트(`7890`)만 제공하여 여러 계정이 동일 IP를 공유하게 되며, 이로 인해 연쇄 계정 차단이 발생합니다.
2. **AI 및 소셜 미디어 위험 제어 블랙박스**: 일반 웹서핑은 가능하지만 Anthropic에서 Cloudflare 1020 차단, Google 인증에서 "중국 리라우팅", Facebook 가입 시 데이터센터 IP 즉시 차단 등의 문제가 발생합니다.
3. **에이전트 제어 불가**: Cursor, Claude Desktop 등의 AI가 로컬 포트의 상태를 파악하지 못해 특정 자동화 환경에 고정 주거용 IP를 할당할 수 없습니다.

**AgentProxyHub**는 업스트림 구독(Clash/Mihomo)을 로컬의 연속적인 독립 포트 풀(SOCKS5 `20001+` / HTTP `30001+`)로 자동 매핑하며, **규칙 기반 다중 시나리오 벤치마크(`scenes.json`)** 및 **표준 MCP 프로토콜**을 지원합니다.

---

### ✨ 주요 특징

- 🔌 **1노드 1전용 포트**: 단일 구독으로 80~120개 이상의 독립 로컬 포트 풀(SOCKS5 & HTTP) 자동 생성.
- 🎯 **시나리오별 정밀 벤치마크**:
  - **✨ Gemini / Antigravity**: Google 공식 지역 인증을 거친 순수 노드 선별.
  - **🟣 Claude 전용**: `api.anthropic.com` 직결 및 Cloudflare 차단 방지.
  - **🟢 ChatGPT / OpenAI**: 고속 API 스트리밍 호환성 검증.
  - **🔵 Facebook / 해외 SNS**: 주거용(Residential) IP 엄격 필터링 및 IP 고정성 유지.
- 🧩 **`scenes.json` 기반의 손쉬운 확장**: 새로운 시나리오(TikTok, Twitter 등)를 몇 줄의 JSON으로 즉시 추가 가능.
- 🤖 **표준 MCP 서버 지원**: Claude Desktop이나 Cursor가 최적 노드를 자율적으로 검색하고 환경에 바인딩.
- 📱 **모바일/LAN 클라이언트 프리 게이트웨이**: 별도 앱 설치 없이 스마트폰이나 태블릿이 컴퓨터의 분기 프록시를 즉시 공유(`192.168.0.107:39999`).

---

### 📦 컴파일된 배포판 다운로드 (권장)

> **복잡한 개발 환경을 설정할 필요가 없습니다! 바로 실행 가능한 완성형 패키지를 제공합니다.**

1. 우측의 **[Releases 페이지](https://github.com/ningnuo-dot/AgentProxyHub/releases)**로 이동;
2. `AgentProxyHub-v1.0.0-windows-x64.zip` 다운로드;
3. 원하는 폴더에 압축 해제;
4. **`启动AgentProxyHub.bat`**를 더블 클릭하면 바로 제어판이 실행됩니다!

---

### 📄 라이선스
이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 배포됩니다.
