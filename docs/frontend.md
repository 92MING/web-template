# 前端开发手册

这个框架的前端能力，核心是“直接服务静态资源”，而不是先假设你一定有一套前端构建链。对很多后台页、管理页、小型站点和原型项目来说，这样更直接。

## 静态目录是怎么挂载的

服务启动时，根站点静态资源来自两部分：

```text
public/                      -> 挂载到 /
extra_public_paths 指定目录  -> 也挂载到 /，并按顺序参与覆盖
```

也就是说，请求 `/about.html` 时，框架会在公开静态目录集合里查找对应文件，而不只是查 `public/` 一个目录。

最常见的默认页面：

- `app/index.html` -> `/`，用于应用自己的默认首页
- `public/about.html` -> `/about.html`

示例项目 `example/e-class` 和 `example/e-shop`，就是通过 `--extra-public-paths` 把自己的 `public/` 目录挂进去的。

查找顺序是：`extra_app_paths` -> `app/` -> `extra_public_paths` -> `public/`。`app/` 侧以 `_` 开头的私有目录不会被 fallback 暴露。

静态 fallback 也支持 Next.js 风格的动态段：

```text
app/posts/_slug_/index.html        ->  /posts/anything
public/articles/_article_id_.html  ->  /articles/anything.html
public/files/_file_id_.txt         ->  /files/report.txt
```

对于 JS/CSS，`.min.js` 与 `.js`、`.min.css` 与 `.css` 会互相回退查找。

## `.m.html` 移动端分支

如果某个页面存在同名 `.m.html` 文件，框架会自动把桌面版和移动版合并成一个响应：

```text
index.html
index.m.html
```

请求 `/index.html` 时，服务端会：

- 读取桌面版 `index.html`
- 读取移动版 `index.m.html`
- 保留桌面版整体 HTML 骨架
- 抽取两边的 `body` 内容
- 注入一段 CSS 和一段脚本
- 用 `#__desktop_branch__` 和 `#__mobile_branch__` 两个容器在前端切换显示

切换条件是前端窗口宽度，小于 `768px` 时显示移动分支。

### 编写建议

- 桌面版写完整 HTML 页面。
- 移动版也可以写完整 HTML；实际合并时，框架只会取它的 `body` 内容作为移动分支。
- 如果两个版本都依赖公共脚本或样式，尽量放在桌面版里统一引入。

## 翻译系统

框架内置了前后端配套的 i18n 机制。

后端注册：

```python
from core.server.translate import register_translation
from core.utils.text_utils import Language

register_translation("welcome", Language.English, "Welcome", category="demo")
register_translation("welcome", Language.SimplifiedChinese, "欢迎", category="demo")
register_translation("welcome", Language.TraditionalChinese, "歡迎", category="demo")
```

前端调用：

```html
<script type="module">
  import { useTranslations } from "/shared/i18n.js";

  const t = useTranslations("demo", document.documentElement.lang || "en");
  await t.ready;
  document.getElementById("title").textContent = t("welcome");
</script>
```

如果你希望页面直接使用静态翻译 dict，而不是走默认的 `/locales/{lang}.json` 或 `/locales/{category}/{lang}.json`，可以给 i18n 实例传自定义路径：

```html
<script type="module">
  import { createTranslator } from "/shared/i18n.js";

  const t = createTranslator({
    lang: document.documentElement.lang || "en",
    path: "/translate.json",
  });
  document.getElementById("title").textContent = await t("welcome");
</script>
```

`path` 支持两种常用格式：

- 单个多语言 dict 文件，例如 `/translate.json`，内容既可以是 `lang -> { key -> text }`，也可以是 `key -> { lang -> text }`
- 带 `{lang}` 占位符的模板路径，例如 `/locales/{lang}.json`

对应的 HTTP 入口是：

```text
GET /locales/{lang}.json
GET /locales/{category}/{lang}.json
```

例如：

```text
GET /locales/zh-cn.json
GET /locales/demo/zh-cn.json
```

`/shared/i18n.js` 还提供这些常用接口：

- `createTranslator()`
- `loadI18n()`
- `requestTranslation()`
- `requestTranslations()`
- `useTranslations()`

## 共享 Web Components

`/shared/components.js` 会自动注册一组 `pt-*` Web Components，不需要额外构建步骤。

最小引入方式：

```html
<script type="module" src="/shared/components.js"></script>
```

当前真实导出的组件远不止两个，常用的包括：

- `pt-data-view`
- `pt-schema-form`
- `pt-modal`
- `pt-toast`
- `pt-confirm`
- `pt-navbar`
- `pt-sidebar`
- `pt-file-uploader`
- `pt-theme-toggle`
- `pt-lang-switcher`

示例：

```html
<pt-data-view searchable page-size="10"></pt-data-view>

<pt-schema-form
  columns="2"
  submit-label="Save"
  schema='[
    {"name":"name","label":"Name","required":true},
    {"name":"email","label":"Email","type":"email"}
  ]'>
</pt-schema-form>

<script type="module">
  import "/shared/components.js";

  document.querySelector("pt-data-view").items = [
    { name: "Alpha", email: "alpha@example.com" }
  ];

  document.querySelector("pt-schema-form").addEventListener("pt-submit", (event) => {
    event.preventDefault();
    console.log(event.detail.value);
  });
</script>
```

组件源码位于：

```text
public/shared/components/
```

## 管理面板资源

管理面板不是从 `public/` 提供，而是从下面这个目录单独挂载：

```text
resources/admin-panel/
```

它对应的 URL 前缀是 `/_internal/admin`，并且受 `internal_path_allowed_ip` 控制。

目录下已经有多套现成页面，例如：

- `panel.html`
- `panel_login.html`
- `storage/`
- `rtc_room/`
- `tools/`

## 一个推荐的前端组织方式

如果你的项目没有单独前端工程，通常这样组织就足够清晰：

```text
public/
  index.html
  index.m.html
  dashboard.html
  dashboard.m.html
  css/
  js/
  assets/
```

如果你需要把业务站点和框架模板解耦，就把这套 `public/` 放在自己的目录里，再通过 `--extra-public-paths` 或 `server_config.extra_public_paths` 挂进去。
