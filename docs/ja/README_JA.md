# Nexting

<div align="center">

**AI駆動のWebクローンツール - 抽出、分析、クローン**

[English](../../README.md) | [中文](../cn/README_CN.md) | 日本語

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

他のツールはスクリーンショットからコードを推測します。私たちは**実際のコード**を抽出します — DOM、スタイル、コンポーネント、インタラクション。数秒でピクセルパーフェクトで保守可能な出力を取得できます。

https://github.com/ericshang98/perfect-web-clone/raw/main/docs/assets/nexting_show_1.mp4

## 目次

- [なぜNexting？](#なぜnexting)
- [機能](#機能)
- [デモ](#デモ)
- [はじめに](#はじめに)
- [アーキテクチャ](#アーキテクチャ)
- [APIリファレンス](#apiリファレンス)
- [技術スタック](#技術スタック)
- [コントリビューション](#コントリビューション)
- [ライセンス](#ライセンス)

## なぜNexting？

### スクリーンショットツール vs コード抽出

ほとんどのAIクローンツールは、ページを画像として見てコードを**推測**します。私たちは**実際のソース**を読み取ります — だから出力は本番環境対応であり、大まかな近似ではありません。

| スクリーンショットベースのツール | Nexting |
|-------------------------------|---------|
| AIがピクセルを解釈 → レイアウトを推測 | 実際のDOMを抽出 → CSSを分析 |
| ハードコードされたピクセル値 | フレキシブルユニットによるレスポンシブ |
| インタラクションなし | ホバーエフェクトとアニメーションを保持 |
| divだらけ | セマンティックHTMLを保持 |
| 保守不可能な出力 | クリーンでモジュラーなコンポーネント |

## 機能

### Webエクストラクター
- **フルページキャプチャ** - Playwrightを使用して完全なDOM構造、CSSスタイル、アセットを抽出
- **テーマ検出** - ライトテーマとダークテーマを自動検出してキャプチャ
- **コンポーネント分析** - AI駆動のコンポーネント境界検出
- **技術スタック分析** - ページで使用されているフレームワークとライブラリを識別
- **アセット抽出** - 画像、フォント、その他のリソースをダウンロード

### クローンエージェント
- **マルチエージェントアーキテクチャ** - 専門エージェントが並列で作業し、より高速で正確な結果を実現
- **AIコード生成** - Claudeが抽出データから本番環境対応のコードを生成
- **ライブプレビュー** - WebContainer（StackBlitz）によるリアルタイムコードプレビュー
- **フレームワークサポート** - React、Next.js、Vue、またはプレーンHTMLにエクスポート

### マルチエージェントシステム

従来のシングルモデルアプローチは複雑なページで失敗します。私たちのマルチエージェントシステムは問題を分解します：

| エージェント | 責任 |
|-------------|------|
| **DOM構造エージェント** | 大規模で深くネストされたDOMツリーを処理。セマンティック構造とコンポーネント境界を抽出。 |
| **スタイル分析エージェント** | 数千のCSSルールを処理。計算されたスタイル、CSS変数、ブレークポイントをキャプチャ。 |
| **コンポーネント検出エージェント** | コードベース全体で再利用可能なパターンを識別し、モジュラーな出力を実現。 |
| **コード生成エージェント** | すべての出力を本番環境対応のフレームワーク固有のコードに合成。 |

## デモ

<div align="center">

https://github.com/ericshang98/perfect-web-clone/raw/main/docs/assets/nexting_show_1.mp4

</div>

## はじめに

### 必要条件

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### クイックスタート

1. **リポジトリをクローン**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **バックエンドのセットアップ**

```bash
cd backend

# 仮想環境を作成
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存関係をインストール
pip install -r requirements.txt

# Playwrightブラウザをインストール
playwright install chromium

# 環境変数を設定
cp ../.env.example .env
# .envを編集してANTHROPIC_API_KEYを追加

# サーバーを起動
python main.py
```

3. **フロントエンドのセットアップ**

```bash
cd frontend

# 依存関係をインストール
npm install

# 環境変数を設定（オプション）
cp ../.env.example .env.local

# 開発サーバーを起動
npm run dev
```

4. **アプリケーションを開く**

ブラウザで [http://localhost:3000](http://localhost:3000) にアクセスしてください。

### 使用方法

#### 1. Webサイトを抽出

1. **Extractor** ページに移動
2. 抽出するURLを入力
3. 抽出オプション（ビューポート、テーマなど）を設定
4. **Analyze** をクリックして抽出を開始
5. 完了したら、**Save to Cache** をクリックして結果を保存

#### 2. AIでクローン

1. **Agent** ページに移動
2. **Sources** ボタンをクリックしてソースパネルを開く
3. キャッシュされた抽出結果を選択
4. AIとチャットしてコードを生成
5. エージェントがコードを書く間、ライブプレビューを確認

## アーキテクチャ

```
nexting/
├── backend/                 # Python FastAPI バックエンド
│   ├── cache/              # 抽出結果のメモリキャッシュ
│   ├── extractor/          # Playwrightベースのウェブエクストラクター
│   ├── agent/              # Claude統合のマルチエージェントシステム
│   ├── boxlite/            # バックエンドサンドボックス環境
│   ├── image_proxy/        # 画像CORSプロキシ
│   └── image_downloader/   # バッチ画像ダウンロードサービス
│
├── frontend/               # Next.js フロントエンド
│   ├── src/app/           # App Routerページ
│   ├── src/components/    # Reactコンポーネント
│   │   ├── ui/           # Shadcn/UIコンポーネント
│   │   ├── landing/      # ランディングページセクション
│   │   ├── extractor/    # エクストラクターコンポーネント
│   │   └── agent/        # エージェントチャット＆プレビュー
│   ├── src/hooks/        # カスタムReact Hooks
│   └── src/lib/          # ユーティリティとAPIクライアント
│
├── docs/                  # ドキュメントとアセット
│   ├── assets/           # デモ動画と画像
│   ├── cn/               # 中国語ドキュメント
│   └── ja/               # 日本語ドキュメント
│
└── .env.example          # 環境変数テンプレート
```

## APIリファレンス

### エクストラクターAPI

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/extractor/extract` | POST | ウェブページ抽出を開始 |
| `/api/extractor/status/{id}` | GET | 抽出ステータスをポーリング |

### キャッシュAPI

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/cache/store` | POST | 抽出結果をキャッシュに保存 |
| `/api/cache/list` | GET | キャッシュされた抽出結果を一覧表示 |
| `/api/cache/{id}` | GET | キャッシュされた抽出結果を取得 |
| `/api/cache/{id}` | DELETE | キャッシュされた抽出結果を削除 |

### エージェントAPI

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/agent/ws` | WebSocket | AIエージェント通信 |

### BoxLite API

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/boxlite/*` | 各種 | バックエンドサンドボックス環境 |
| `/api/boxlite-agent/*` | 各種 | エージェントサンドボックス操作 |

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| **フロントエンド** | Next.js 15, React 19, TailwindCSS 4, Shadcn/UI, Three.js |
| **バックエンド** | FastAPI, Python 3.11+, Playwright, WebSocket |
| **AI** | Claude (Anthropic API), マルチエージェントアーキテクチャ |
| **プレビュー** | WebContainer (StackBlitz) |
| **スタイリング** | TailwindCSS, CSS変数, ダークモードサポート |

## コントリビューション

コントリビューションは大歓迎です！お気軽にPull Requestを送ってください。

1. リポジトリをフォーク
2. フィーチャーブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. Pull Requestを開く

## ライセンス

このプロジェクトはMITライセンスの下でライセンスされています - 詳細は [LICENSE](../../LICENSE) ファイルを参照してください。

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - 推測ではなく、実際のコードを抽出。

[Eric Shang](https://github.com/ericshang98) が ❤️ を込めて作成

</div>
