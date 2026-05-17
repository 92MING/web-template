# Example Projects

These projects demonstrate how to use the proj-template framework with `extra_app_paths` and `extra_public_paths`.
They can also reuse framework public helpers such as `/shared/i18n.js`, which loads translation catalogs from `/locales/{lang}.json` or `/locales/{category}/{lang}.json` by default, or from a custom static catalog like `/translate.json` when a page passes `path` to `createTranslator()`.

## e-Shop

A simple e-commerce demo.

```bash
cd e-shop
python run.py
```

Features:

- Product listing (`GET /api/shop/products`, `GET /api/shop/products/{product_id}`)
- Cart (`GET/POST /api/shop/cart`)
- Orders (`GET/POST /api/shop/orders`, `GET /api/shop/orders/{order_id}`)
- AI chat (`POST /api/shop/ai-chat`)
- User profile (`GET /api/shop/user/profile`)
- Checkout (`POST /api/shop/checkout`)

## e-Class

An online classroom demo.

```bash
cd e-class
python run.py
```

Features:

- Student: check-in, homework list/upload, grades, materials, announcements
- Teacher: homework management, grade submissions, materials upload, student management, analytics, announcements
- RTC classroom (`POST /api/classroom/{class_id}/rtc/start`)
- Chat room (`GET/POST /api/classroom/{class_id}/chat`)
- Courses (`GET /api/classroom/{class_id}/courses`, `GET /api/classroom/{class_id}/courses/{course_id}`)

## WebRTC Room

A minimal Zoom-style meeting demo built on top of the built-in webrtc-chatroom plugin.

```bash
cd webrtc-room
python run.py
```

Features:

- Extremely simple landing page with `Create Room` / `Join Room`
- Create flow jumps directly into the meeting view
- Room page auto-generates a shareable join URL after connection
- Guests can join by direct URL or by room number + password

## How Examples Work

Both examples use `create_app(config=config)` to inject their own directories:

```python
config = Config()
config.server_config.extra_app_paths = [str(HERE)]
config.server_config.extra_public_paths = [str(HERE / "public")]
config.plugin_configs["webrtc-chatroom"] = {"enabled": True}  # e-class enables this
app = create_app(config=config)
uvicorn.run(app, host="127.0.0.1", port=8000, workers=2)
```

This keeps business code separate from the framework template.
