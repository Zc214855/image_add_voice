# Git 提交推送记录

- 阶段：准备
- 操作：新增 `.gitignore`
- 规则：排除 `output/`、`story_video_tool/.cache/`、Python 缓存、虚拟环境、日志和临时文件
- 原因：`output/妈妈买绿豆.mp4` 超过 GitHub 单文件限制，必须作为可再生成产物排除

- 阶段：本地提交
- 分支：`main`
- 提交：`7e5e7e4 Initial story video tool`

- 阶段：远程推送
- 远程：`git@github.com:Zc214855/image_add_voice.git`
- 分支：`main`
- 结果：已推送并设置 upstream

- 阶段：推送报错排查
- 现象：用户将 `output/` 加入版本控制后，本地 `main` 超前远程 1 个提交
- 原因：`output/妈妈买绿豆.mp4` 为 259225158 字节，超过 GitHub 普通 Git 单文件 100MB 限制
- 处理策略：使用 Git LFS 跟踪 `output/*.mp4`，避免普通 Git 对象包含大视频
- 结果：已新增 `.gitattributes`，2 个 mp4 以 LFS 对象上传，远程 `main` 推送成功
