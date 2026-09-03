# Androidアプリ運用手順

このAndroidアプリはCapacitorで本番サイト `https://kifu-comment-lab.com` を表示する。
Web版を更新するとAndroid版にも反映され、PWAとしてホーム画面からも利用できる。

## 前提

- Node.jsとnpm
- Android Studio（Android SDK、JDK 21）
- 本番サイトの有効なHTTPS
- Google Play Consoleアカウント

## Web/PWAとAndroidの同期

```bash
cd frontend
npm ci
npm run build
npm run android:sync
```

Android Studioで確認する場合:

```bash
npm run android:open
```

CLIでデバッグAPKを作る場合:

```bash
npm run android:debug
```

生成物は `frontend/android/app/build/outputs/apk/debug/app-debug.apk`。

## Google Play向けAAB

署名鍵はGitへ保存しない。本番用keystoreとパスワードを安全な秘密管理へ置き、
Android Studioの **Build > Generate Signed App Bundle or APK** から署名済みAABを作成する。
Play ConsoleへはAPKではなくAABを登録する。

## 更新方法

- Web画面・APIだけの変更: 通常どおりサイトをデプロイする。
- Capacitor設定、Android権限、アプリアイコンの変更: `npm run android:sync` 後に新しいAABを公開する。
- PWAキャッシュを変更する場合: `public/sw.js` の `CACHE_NAME` を更新する。

## 公開前の確認事項

- メール登録、ログイン、ログアウト
- Googleログイン（埋め込みWebView制限があるため実機確認必須）
- KIF/KI2/CSA/TXTのファイル選択と投稿
- Androidの戻る操作と画面回転
- オフライン画面からの復帰
- Stripe契約済みアカウントでAI解説が表示されること

AndroidアプリではGoogle Playの支払いポリシーに配慮し、Stripeでの新規契約・契約管理ボタンを表示しない。
アプリ内で新規購読を提供する場合は、Google Play Billingとバックエンド側の利用権同期を別途実装する。
