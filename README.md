# 自然言語で指示できるAI仕分けロボット

ROS 2 Humble、MoveIt 2、Gazebo Classic、Ollamaを組み合わせたロボットシミュレーションです。ユーザーが日本語または英語で指示すると、ローカルLLMが対象キューブと仕分け先を判断し、UR3ロボットとRobotiq 2F-85グリッパーがピック＆プレースを実行します。実機は使用しません。

## 特徴

- 自然言語指示をローカルLLM（既定値: `qwen2.5:3b`）で解釈
- LLM出力を限定JSONに変換し、色と仕分け先を検証してから動作
- UR3、Robotiq 2F-85、MoveIt 2による経路計画
- Gazebo上に作業台、3色のキューブ、左右の仕分けマットを自動生成
- キューブの実位置を把持直前に再取得し、ずれを補正
- 把持・搬送・配置時の姿勢と指先位置を校正
- DockerとnoVNCにより、Windows上でもブラウザから再現可能

## システム構成

```text
自然言語指示
    ↓
Ollama / qwen2.5:3b
    ↓  制約付きJSON {color, destination}
入力検証（許可された色・仕分け先のみ）
    ↓
ROS 2 PickPlaceノード
    ↓
MoveIt 2 / ros2srrc Action
    ↓
Gazebo（UR3 + Robotiq 2F-85）
```

対応する色は `red`、`blue`、`yellow`、仕分け先は `left`、`right` です。曖昧な指示や未対応の値ではロボットを動かしません。

## 動作確認環境

- Windows 11
- Docker Desktop（WSL 2 backend）
- Docker Compose v2
- Ollama
- ブラウザ（noVNC表示用）

Docker DesktopのWindows要件とインストール方法は[公式ドキュメント](https://docs.docker.com/desktop/setup/install/windows-install/)を参照してください。本構成は `linux/amd64` のシミュレータを使用するため、ARM64ホストではエミュレーションにより動作が遅くなる場合があります。

## セットアップ

### 1. リポジトリを取得

```bash
git clone https://github.com/Kosuke-Nagao/ai-sorting-robot.git
cd ai-sorting-robot
```

### 2. Ollamaとモデルを準備

Windows PowerShellでOllamaをインストールします。すでにインストール済みの場合は不要です。

```powershell
irm https://ollama.com/install.ps1 | iex
ollama pull qwen2.5:3b
```

Ollamaを起動し、次で確認します。

```powershell
ollama --version
curl.exe http://localhost:11434/api/tags
```

OllamaのWindows向け最新手順は[公式ダウンロードページ](https://ollama.com/download/windows)を参照してください。

### 3. Dockerイメージをビルド

Docker Desktopを起動してから、リポジトリのルートで実行します。初回はROS 2、MoveIt 2、Gazebo関連の依存関係を取得するため時間がかかります。

```bash
docker compose build --progress=plain
```

### 4. シミュレータを起動

```bash
docker compose up -d --no-build --pull never
```

ブラウザで次を開き、ロボット、作業台、キューブが表示されるまで待ちます。

<http://localhost:6080/vnc.html?autoconnect=1&resize=scale>

起動状態は次で確認できます。

```bash
docker compose ps
docker compose logs --tail=30 simulator
```

## 実行方法

### LLMの判断だけを確認（ロボットは動かさない）

```bash
docker compose exec -T simulator bash -lc \
"source /opt/ros/humble/setup.bash && \
 source /opt/robot_ws/install/setup.bash && \
 source /workspace/install/setup.bash && \
 ros2 run ai_sorting_robot natural_sort -- \
 --dry-run '赤いキューブを左へ'"
```

成功例:

```text
LLM decision: color=red, destination=left
```

### 自然言語で仕分けを実行

```bash
docker compose exec -T simulator bash -lc \
"source /opt/ros/humble/setup.bash && \
 source /opt/robot_ws/install/setup.bash && \
 source /workspace/install/setup.bash && \
 ros2 run ai_sorting_robot natural_sort -- \
 '黄色いキューブを右へ'"
```

最後に次が表示されれば成功です。

```text
SUCCESS: yellow cube was moved to the right zone.
```

### LLMを使わず、色と仕分け先を直接指定

```bash
docker compose exec -T simulator bash -lc \
"source /opt/ros/humble/setup.bash && \
 source /opt/robot_ws/install/setup.bash && \
 source /workspace/install/setup.bash && \
 ros2 run ai_sorting_robot pick_place -- \
 --color red --destination left"
```

### 作業台とキューブを初期状態へ戻す

```bash
docker compose exec -T simulator bash -lc \
"source /opt/ros/humble/setup.bash && \
 source /opt/robot_ws/install/setup.bash && \
 source /workspace/install/setup.bash && \
 ros2 run ai_sorting_robot spawn_workcell"
```

## モデルや接続先の変更

既定値は次の環境変数で変更できます。

```bash
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

PowerShellから変更する例:

```powershell
$env:OLLAMA_MODEL="qwen2.5:3b"
docker compose up -d --no-build --force-recreate
```

APIキーやクラウドサービスは不要です。自然言語の指示はホスト上のOllamaへ送信されます。

## 停止

```bash
docker compose down
```

## ディレクトリ構成

```text
.
├── compose.yaml
├── Dockerfile
├── dependencies.repos
├── docker/
│   ├── entrypoint.sh
│   └── simplify_robotiq_visuals.py
├── docs/
│   ├── create_submission_report.py
│   └── 説明資料_PAI最終課題_honor.docx
└── src/ai_sorting_robot/
    ├── package.xml
    ├── setup.py
    └── ai_sorting_robot/
        ├── command_schema.py
        ├── llm_parser.py
        ├── natural_sort.py
        ├── pick_place.py
        └── spawn_workcell.py
```

## 主な実装

- `llm_parser.py`: Ollamaへの問い合わせ、JSON化、曖昧指示の拒否
- `natural_sort.py`: 自然言語入力からロボット実行までの入口
- `command_schema.py`: 色と仕分け先の許可リストおよび検証
- `pick_place.py`: 経路計画、グリッパー制御、把持・搬送・配置
- `spawn_workcell.py`: 作業台、仕分けマット、3色キューブの生成
- `Dockerfile`: ROS/Gazebo/MoveIt環境と依存リポジトリの固定

## 再現性と既知の制約

- 外部ROS依存リポジトリは `dependencies.repos` でコミットを固定しています。
- Gazebo Classicはソフトウェアレンダリングで動作するため、実時間係数が1未満になる場合があります。
- 安定したデモのため、Gazeboのリンクアタッチ機能を使って把持を保持しています。
- 本システムはシミュレーション専用です。実機で使用する場合は安全設計と再調整が必要です。

## 課題レポート

提出用の説明資料は `docs/説明資料_PAI最終課題_honor.docx` に含めています。詳細なレポート原稿は提出物として別管理し、公開リポジトリには含めていません。

## 第三者コンポーネント

ビルド時に取得するROSパッケージは `dependencies.repos` に記載しています。各コンポーネントの著作権とライセンスは、それぞれの配布元に帰属します。本リポジトリ自身のコードは[Apache License 2.0](LICENSE)で公開します。
