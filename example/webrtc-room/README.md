# WebRTC Room Example

一个最小的 Zoom 风格会议示例。

运行方式：

```bash
cd example/webrtc-room
python run.py
```

功能：

- 首页只有“创建房间 / 加入房间”两个主入口
- 创建房间后直接进入会议画面
- 会议页面会生成可直接分享的链接
- 其他用户既可以直接点分享链接进入，也可以输入房间号和密码加入
- 底层音视频与房间管理复用内置 webrtc-chatroom 插件