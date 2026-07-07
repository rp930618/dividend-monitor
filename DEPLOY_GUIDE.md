# 红利策略 v8 监测脚本 — 部署指南

## 一、仓库结构

```
dividend-monitor/
├── main.py                      # 核心监测脚本
├── config.yaml                  # 策略配置文件
├── requirements.txt             # Python 依赖
├── DEPLOY_GUIDE.md             # 本部署指南
└── .github/
    └── workflows/
        └── daily-monitor.yml    # GitHub Actions 工作流
```

## 二、环境变量配置

在 GitHub 仓库的 **Settings → Secrets and variables → Actions → Repository secrets** 中添加：

| Secret 名称 | 必填 | 说明 |
|------------|------|------|
| `WECHAT_WEBHOOK_URL` | 是 | 企业微信机器人 Webhook URL |

### 获取企业微信 Webhook URL

1. 打开企业微信，进入目标群聊
2. 点击右上角「...」→「添加群机器人」→「新创建一个机器人」
3. 复制 Webhook 地址（格式：`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx`）
4. 将地址粘贴到 GitHub Secrets 中

## 三、GitHub 仓库设置

### 3.1 创建仓库

1. 在 GitHub 上新建一个私有仓库（如 `dividend-monitor-v8`）
2. 将本目录下的所有文件推送至仓库：

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/dividend-monitor-v8.git
git add .
git commit -m "v8 initial commit"
git push -u origin main
```

### 3.2 启用 Actions

1. 进入仓库 → **Actions** 标签页
2. 如果看到 "Workflows aren't being run on this repository"，点击 **I understand my workflows, go ahead and enable them**
3. 确保 `daily-monitor.yml` 已列出

## 四、定时任务设置

已在 `.github/workflows/daily-monitor.yml` 中配置：

```yaml
on:
  schedule:
    - cron: '30 5 * * 1-5'   # UTC 05:30 = 北京时间 13:30（周一至周五）
```

**说明**：
- GitHub Actions 使用 UTC 时间，UTC 05:30 = 北京时间 13:30
- `1-5` 表示周一至周五（排除周末）
- 如果需要调整时间，修改 cron 表达式即可

### 手动触发

除定时运行外，支持手动触发：
1. 进入仓库 → **Actions** → **Dividend Strategy v8 Daily Monitor**
2. 点击右上角 **Run workflow** → 选择分支 → 点击 **Run workflow**

## 五、本地运行与测试

### 5.1 安装依赖

```bash
cd dividend-monitor
pip install -r requirements.txt
```

### 5.2 配置环境变量（本地测试）

```bash
export WECHAT_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
```

### 5.3 运行脚本

```bash
python main.py
```

### 5.4 预期输出

```
============================================================
红利策略监测 v8 - 2026-07-05 13:30
============================================================
[数据] 获取 9 只标的数据
[评分] 招商银行: 62.5  |  红利低波50ETF: 58.3  |  长江电力: 55.8 ...
[风控] 600011 华能国际 触发基本面红线:
       - 净利润连续2年下降
       - ROE连续3年低于阈值
       → 进入90天观察期
[重分配] 将 600011 的 9% 权重分配给其他标的
[现金] ERP=5.95% 现金比例 10%
[容差] 无调仓信号（均在5/25容差内）
[DDCA] 000651 格力电器 触发被动补仓（月跌幅3.2%）
[DDCA] 601006 大秦铁路 触发被动补仓（月跌幅5.1%）
[报告] 生成日报，共 15 条消息
[推送] 日报推送成功
============================================================
```

## 六、日志查看方式

### 6.1 GitHub Actions 日志

1. 进入仓库 → **Actions**
2. 点击最近的一次运行记录
3. 展开 `Run dividend monitor` 步骤查看详细输出

### 6.2 日志文件

脚本运行后会生成 `dividend_monitor.log` 文件：

```bash
# 本地查看
tail -f dividend_monitor.log

# GitHub Actions 中下载
# Actions 运行完成后，在 Artifacts 中下载 monitor-logs-{run_id}.zip
```

### 6.3 日志轮转

脚本使用 Python `logging.handlers.RotatingFileHandler`，默认配置：
- 单个日志文件最大 5MB
- 保留最近 5 个备份文件
- 日志级别：INFO

## 七、常见问题排查

### 7.1 AKShare 数据获取失败

**现象**：日志中出现 `AKShare 数据获取失败，使用静态兜底数据`

**原因**：GitHub Actions 运行环境或本地网络无法访问 AKShare 数据源

**解决**：脚本已内置静态兜底数据，无需额外操作。如需真实数据，建议在本地有稳定网络的环境运行。

### 7.2 企业微信推送失败

**现象**：日志中出现 `[微信] 推送失败`

**排查步骤**：
1. 检查 `WECHAT_WEBHOOK_URL` 是否正确配置
2. 在企业微信群中点击机器人头像，确认没有被移出群聊
3. 测试 Webhook：
   ```bash
   curl -X POST "$WECHAT_WEBHOOK_URL" \
     -H 'Content-Type: application/json' \
     -d '{"msgtype":"text","text":{"content":"测试消息"}}'
   ```

### 7.3 GitHub Actions 未按时运行

**现象**：定时任务没有触发

**原因**：GitHub Actions 的 cron 调度可能有延迟（通常不超过 1 小时）

**解决**：
1. 检查仓库的 Actions 是否被禁用（Settings → Actions → General）
2. 如果仓库 60 天无活动，GitHub 可能暂停 Actions。手动触发一次即可恢复

### 7.4 配置文件修改

如需修改策略参数（如权重、阈值），编辑 `config.yaml` 后重新推送：

```bash
git add config.yaml
git commit -m "调整风控阈值"
git push
```

无需修改代码，所有参数均从 `config.yaml` 读取。

## 八、更新与维护

| 维护项 | 频率 | 操作 |
|--------|------|------|
| 检查日志 | 每周 | 查看 GitHub Actions 运行记录 |
| 校验 Webhook | 每月 | 测试企业微信推送是否正常 |
| 更新基本面数据 | 每半年 | 更新 `main.py` 中的静态兜底数据 |
| 策略复盘 | 每半年 | 与半年度调仓同步，评估策略表现 |
| 依赖更新 | 每季度 | 检查 `requirements.txt` 中的依赖是否有安全更新 |

## 九、联系与反馈

如有问题，请通过以下方式反馈：
- 在 GitHub 仓库中提交 Issue
- 查看日志文件定位问题
- 检查企业微信推送的日报内容

---

**文档版本**: v8 Final  
**最后更新**: 2026-07-05
