# 10song.com 客户留言监控

自动监控 [10song.com/contact](https://www.10song.com/contact) 页面的客户提交信息，发现新客户自动推送微信通知。

## 工作原理

1. GitHub Actions 每 30 分钟自动运行
2. Playwright 渲染 SPA 页面（切换中文版）
3. 解析"提交信息记录"区域客户条目
4. 对比基线，发现新客户推送微信通知（Server酱）
5. 更新基线文件

## 设置步骤

1. Fork 或创建此仓库
2. 在仓库 Settings → Secrets → Actions 中添加：
   - `SENDKEY`: 你的 Server酱 SendKey
3. 启用 Actions（仓库 Settings → Actions → General → Allow all actions）
4. 等待自动运行，或手动触发（Actions → Run workflow）

## 手动触发

在 Actions 页面点击 "Run workflow" 按钮即可。

## 基线更新

基线文件 `baseline.json` 通过 artifact 持久化，每次运行后自动上传更新。
