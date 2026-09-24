# タスク管理システム

正式仕様は `specs/`、開発計画は `development_plan.md`、再開時の状況は `development_progress.yaml` を参照してください。

## 別のPCから再開する場合

このリポジトリのファイル一式を別PCへコピーまたは共有リポジトリから取得してください。最初に `development_progress.yaml` の `current_phase`、`gate`、`next_actions`、`pending_question`、`verification_results` を確認します。正式仕様は `specs/`、作業順序は `development_plan.md` が基準です。

`.env.development` はGit対象外のマシン固有の秘密情報です。別PCでは内容をコピーせず、`python3 execute/prepare-development.py` でそのPC用に新しく生成してください。開発DB・画像はDockerボリュームに保存されるため、通常のGit取得では引き継がれません。必要なデータがある段階では、別途バックアップと復元手順を決めてから移行します。現時点ではP1の共通画面だけで、移行対象の業務データはありません。

別PCのDocker EngineとComposeが利用できることを確認後、通常の起動手順を実行します。ポートはそのPCの `127.0.0.1:8000` を使用します。

## ローカル開発環境

このマシンのDocker EngineとComposeを使用します。DjangoとPostgreSQLを別コンテナで起動し、Google Chromeで `http://127.0.0.1:8000` を開きます。DBはホストへ公開しません。

```bash
python3 execute/prepare-development.py
bash execute/start-development.sh
bash execute/test-development.sh
```

再起動と永続化を確認する場合は `python3 execute/verify-development.py` を実行します。開発用コンテナを再起動し、検証用DBレコードとファイルの保持を確認してから検証データを除去します。

秘密値は初回のみ `.env.development` に生成されます。このファイルはGit対象外です。起動のたびに秘密値を作り直さないでください。

停止は次のコマンドです。DB・画像の永続ボリュームは保持されます。

```bash
bash execute/stop-development.sh
```

コード変更後は起動シェルを再実行すると再ビルドします。開発環境はDjango開発サーバーを使用し、本番公開の構成ではありません。

## P1の確認範囲

- ホームの基本配置と日本時間表示
- `/health/` でアプリとDBの接続確認
- 起動・停止・再起動後の永続化
- 開発コンテナ内の一時テストDBを用いた機能テスト

認証と業務画面は後続フェーズで追加します。現在の共通画面にユーザー情報や業務データは表示しません。

動作ログはコンテナごとに10MB×3ファイルでローテーションします。後続で実装する監査ログの無期限保持とは別です。ログを確認する場合は次のコマンドを使用します。

```bash
docker compose --env-file .env.development -f compose.development.yaml logs --tail=100
```

ボリューム削除を伴う操作は通常の起動・停止手順に含みません。バックアップ・復旧方針と本番構築は保留です。

依存関係は[Djangoのサポート表](https://www.djangoproject.com/download/)、[Python互換表](https://docs.djangoproject.com/en/5.2/faq/install/)、[PostgreSQLドライバー要件](https://docs.djangoproject.com/en/5.2/ref/databases/)を確認して選定しています。実際の固定版は `specs/05_infra_spec.yaml` とイメージ・依存定義を参照してください。
