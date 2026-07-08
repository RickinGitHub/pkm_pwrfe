---
l1: 科技
l2: AI
l3: 研发体系
title: Google TV软件认证表SOP
fetched_at: '2026-07-07T14:51:48.509651'
categories:
- l1: 科技
  l2: AI
  l3: 研发体系
- l1: 科技
  l2: AI
  l3: 模型
- l1: 科技
  l2: 终端
  l3: 形态
---

# Google TV软件认证表SOP

> pageId: 645728847 | 导出时间: 2026-07-07T14:51:48.509694

| 认证项 | 区域 | 类型 | 开发&测试 | 认证周期 | 测试团队（自测或实验室测试（Regime）） | 授权代理机构 | 认证测试实验室 | 负责部门 | 产品SE需要关注事项 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **全球认证** |  |  |  |  |  |  |  |  |  |  |
| CI+1.4&2.0 | Global | Content Control | TCL 内部开发：4周  SQA 测试：8周 | 18w | Regime | CI+ LLP  | Eurofins  | 基础软件一部 | 由基础软件部负责认证，认证经理定认证计划  产品SE配合出版本，关注认证进度 | CI+ 规格强制  2K :CI+;  4K: CI+ with ECP  |
| XTS | Global | System | TCL 内部开发：6周  SQA 测试：6周 | 16w | Regime | Google | Google | 定制开发部 | 直接在量产上认证  1.项目经理和认证经理定认证计划  2.定制开发部会主导认证测试，产品SE配合提供产品配置信息  3. 配合发布认证测试版本，提测认证测试团队  4. 关注认证进度，保障量产前通过认证 |  |
| YouTube | Global | VoD | TCL 内部开发：6周  SQA 测试：6周 | 16w | Regime | YouTube  | YouTube  | 定制开发部 | 直接在量产上认证  1.项目经理和认证经理定认证计划  2.定制开发部会主导认证测试，产品SE配合提供产品配置信息  3. 配合发布认证测试版本，提测认证测试团队  4. 关注认证进度，保障量产前通过认证 |  |
| Netflix  | Global | VoD | TCL 内部开发：6周  SQA 测试：6周 | 16w | Regime | Netflix  | Netflix  | 定制开发部 | Netflix需要单独拉分支跑认证  1.项目经理和认证经理定认证计划  2.定制开发部会主导认证测试，产品SE配合提供产品配置信息  3. 关注认证进度，保障量产前通过认证 |  |
| Amazon Prime Video  | Global | VoD | TCL 内部开发：4周  SQA 测试：4周 | 12w | Regime | Amazon  | Amazon Development Centre London | 定制开发部 | 直接在量产上认证  1.项目经理和认证经理定认证计划  2.定制开发部会主导认证测试，产品SE配合提供产品配置信息  3. 配合发布认证测试版本，提测认证测试团队  4. 关注认证进度，保障量产前通过认证 |  |
| Airplay 2 | Global | IoT | TCL 内部开发：6周  SQA 测试：6周 | 20w | Regime | Apple | US | 产品软件部 | 1.认证经理制定认证计划  2. 产品软件部负责airplay apk集成，系统烧key部分集成，bct wifi特殊修改，静默待机特殊修改  3. 前期认证跟随主干，后期需要拉认证分支  4. 产品SE需要关注量产前在代码上将airplay key的访问地址改为正式服务器的 |  |
| Freesync | Global |  |  | 20w | Regime | AMD | Canada | 硬件 | 由硬件开发代表发起认证，接口人安排测试，提交报告给认证经理  产品SE配合发版本，关注认证进度即可 | Freesync  Freesync Premium |
| DolbyVision | Global |  |  |  | Regime | Dolby | Shenzhen  US | 硬件—画质 |  |  |
| VUDU | US, Mexico | VoD |  | 12w | Regime | Walmart |  | 项目部—认证组 | VUDU不用外送，只用报备，申请白名单  产品SE帮助提供产品信息，关注量产前完成认证即可 | 外送认证报告 |
| MS12  | Global | Audio | TCL 内部开发：4周  SQA 测试：4周 | 12w | Regime | Dolby | Shenzhen | 硬件—电声 | 由硬件统一安排认证  1.产品SE配合拉分支，发版本，提供产品信息等  2.认证相关问题需要帮助硬件推动，SOC问题需要帮忙推动  3.关注认证进度，有风险及时HL硬件，保障量产前通过认证 |  |
| Dolby Atmos  | Global | Audio | TCL 内部开发：4周  SQA 测试：4周 | 12w | Regime | Dolby | Shenzhen | 硬件—电声 | 由硬件统一安排认证  1.产品SE配合拉分支，发版本，提供产品信息等  2.认证相关问题需要帮助硬件推动，SOC问题需要帮忙推动  3.关注认证进度，有风险及时HL硬件，保障量产前通过认证 | Dolby Atmos 包含在MS12认证中 |
| Google ART (far-Filed) | NZ,AU DE,ES,IT,GB,FR,SECA,US,MX,BRJP,KR,IN | IoT |  | 20w | Regime | Google  | UL （US）  | 硬件 | 由硬件负责认证，认证经理协助外送报告  产品SE关注认证进度即可 |  |
| HDMI  | Global |  |  | 20w | Regime | Dolby | Shenzhen | 硬件 | 由硬件负责认证，仅需配合硬件 |  |
| **欧洲认证** |  |  |  |  |  |  |  |  |  |  |
| Numericable | France | DVB-C |  |  | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 一致性符合测试，场测 |
| Fransat | France | DVB-S |  |  | Regime | Fransat | Fransat |  |  | 2022 取消外送 |
| Cable Ready HD | Finland | DVB-C |  | 3w | Regime | Cable Ready HD | Labwise | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| Antenna Ready HD | Finland | DVB-T2 |  | 3w | Regime | Antenna Ready HD | Labwise | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| BOXER HD | Sweden, Denmark | DVB-T2 |  |  | Regime | BOXER HD | Teracom IRD Testing |  |  |  |
| RiksTV | Norway | DVB-T |  |  | Regime | RiksTV | Teracom IRD Testing |  |  |  |
| SAORVIEW | Ireland | DVB-T |  |  | Regime | SAORVIEW | Teracom IRD Testing |  |  |  |
| Com Hem | Sweden | DVB-C |  |  | Regime | Com Hem | Eurofins  |  |  |  |
| YouSee | Denmark | DVB-C |  |  | Regime | YouSee |  |  |  |  |
| HD+ | Germany | DVB-S/S2 |  | 3w | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| Kabel Deutschland | Germany | DVB-C |  |  | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| Kabel BW | Germany | DVB-C |  |  | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| Unity Media | Germany | DVB-C |  |  | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 |  |
| nc+ | Poland | DVB-S/S2 |  |  | Regime |  |  |  |  |  |
| Ziggo | The Netherlands | DVB-C |  |  | Regime | UPC  | Ziggo  |  |  |  |
| Freeview HD | UK | DVB-T2 |  |  | Regime | Freeview Play | DTG  | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 只Freeview Play 需要时外送 |
| Freeview Play | UK | DVB+ VoD |  |  | Regime | Freeview Play | DUK/DTG/BBC | 基础软件一部 |  | 每年更新Spec  |
| BBC iPlayer | UK | VoD |  |  | Regime | BBC | BBC | 基础软件一部 |  |  |
| FreeviewPlus (AU) | AU | HbbTV |  |  | Regime | Freeview Play | Eurofins  | 基础软件一部 |  |  |
| Freeview Plus (NZ) | New Zealand | DVB-T |  |  | Regime | Freeview Play | Eurofins  | 基础软件一部 |  |  |
| Tivu Sat （Italy） | Italy | DVB-S |  |  |  |  |  |  |  | Lativu 4K & Lativeu |
| LovesTV | Spain | DVB |  |  | Regime |  | LovesTV |  |  | 外送 |
| M7 | Czech Republic | DVB |  |  | Regime |  | M7 |  |  | 外送 |
| DIGI | Romania | DVB |  |  | Regime |  | DIGI |  |  | 外送 |
| **亚太认证** |  |  |  |  |  |  |  |  |  |  |
| SIRIM | Malaysia  | DVB-T2 | TCL 内部开发：6周  SQA 测试：6周 | 16w | Regime | SIRIM | Allion |  |  | 强制认证，按PCB layout  |
| NBTC | Thailand  | DVB-T2 |  | 2w | self-test | NBTC | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 2022.6 取消OAD测试,海关准入要求 |
| VNC | Viet Nam  | DVB-T |  | 2w | self-test | VNC | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 强制认证，输出自测报告 |
| 新加坡DVB-T2 | Singapore | DVB-T2 |  | 2w | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 强制认证，输出自测报告 |
| 阿联酋DVB-T2 | United Arab Emirates  | DVB-T2 |  | 2w | self-test | self-test | self-test | 项目部—认证组  测试部—认证组 | 自测试，仅需要交认证报告  产品SE负责配合认证经理提供认证软件 | 强制认证，输出自测报告 |
| SDPPI-EWS | Indonesia | DVB-T2 |  |  | Regime |  |  |  |  | 强制认证，输出自测报告  海关准入要求 |
| 腾讯云游戏 | China |  |  |  | self-test | Tencent | Shenzhen |  |  | 芯片平台加白名单  满足合作商市场巡检要求  2星，3星，4星 |
