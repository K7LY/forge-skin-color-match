# Forge Skin Color Match

Stable Diffusion WebUI ForgeのInpaintで、生成した肌の色を周囲に合わせる拡張機能です。
元画像の肌色を参照し、編集した部分の赤み・黄み・明るさを整えます。
Forge同梱のライブラリを使い、CPUで動作します。

## インストール

Forgeの **Extensions → Install from URL** からインストールできます。入力するURLはこちらです。

```text
https://github.com/K7LY/forge-skin-color-match
```

インストール後にForgeを再起動すると、img2img画面に **Skin Color Match** パネルが表示されます。
Gitで管理する場合は、Forgeのルートディレクトリで次のコマンドが使えます。

```sh
git clone https://github.com/K7LY/forge-skin-color-match extensions/forge-skin-color-match
```

## 基本的な使い方

`img2img → Inpaint` で元画像と編集マスクを設定し、**Enable Skin Color Match** をONにすると、
生成後の画像に補正がかかります。初めは **Reference Mode: Auto** がおすすめです。
編集部分に近い肌から参照色を選び、マスク内の肌に色を合わせます。

初期設定は**一致優先**です。**Correction Strength** と **Brightness Correction** がともに1.0で、
肌の平均色と明るさを参照に合わせます。変化を控えめにしたい場合はCorrection Strength、
明るさを元の生成結果に寄せたい場合はBrightness Correctionを下げて調整できます。

更新前の設定が画面に残っている場合は、この2項目を1.0にすると一致優先の設定になります。

Forge標準の `img2img color correction` がOFF、`overlay_inpaint` がONの設定で利用できます。
Only masked／Whole pictureの両方に対応しています。

## 肌色の範囲を調整する

**Skin Color Range (LAB)** では、肌として扱う色の範囲を設定できます。
指定したa/b範囲と、明度・暖色系の条件を満たすピクセルが参照と補正の対象になります。

| 設定 | 初期範囲 | 色の方向 |
| --- | --- | --- |
| Skin a Minimum / Maximum | −2〜42 | 小さいほど緑寄り、大きいほど赤寄り |
| Skin b Minimum / Maximum | 0〜50 | 小さいほど青寄り、大きいほど黄色寄り |

たとえば、黄色やオレンジ色の服が肌として拾われる場合は、**Skin b Maximum** を下げると
対象を絞れます。範囲を狭めるほど背景や衣服を除きやすくなり、広げるほど色の異なる肌を拾いやすくなります。
元画像の肌と生成部分の肌が、どちらも範囲に収まる設定が目安です。

肌色に近い服や背景がある画像では、次のManual参照も役立ちます。

## 参照する肌を指定する

**Reference Mode: Manual** を選ぶと、参照マスクのアップロード欄が表示されます。
元画像と同じサイズ・同じ配置の白黒マスクを使い、参照したい肌を白、それ以外を黒で示します。
透明PNGではアルファが参照範囲になります。

補正には、そのマスクが示す元画像の肌色が使われます。
複数人が写る画像で特定の人物の肌色に合わせたいときや、編集部分のすぐ近くに肌がないときに便利です。
参照範囲にもSkin Color Rangeの設定が適用されます。

## 設定一覧

| 設定 | 初期値 | 調整の目安 |
| --- | --- | --- |
| Enable Skin Color Match | OFF | ONでInpaint後の補正が有効になります |
| Correction Strength | 1.0 | 0〜1。1で平均色を参照に合わせ、0で補正をOFFにします |
| Reference Radius | 48px | 1〜256px。周囲の肌を探す範囲です |
| Mask Feather | 24px | 0〜128px。補正を境界になじませる幅の上限です |
| Brightness Correction | 1.0 | 0〜1。1で平均明度も合わせ、0で元の明度を保ちます |
| Color Space | LAB | 明度と色味を分けて調整します |
| Reference Mode | Auto | Autoは近くの肌、Manualは指定した肌を参照します |

肌の内部には一定のLAB色差を加えるため、陰影の強弱やきめを保ちながら色を合わせられます。
フェザー幅は肌領域の太さに合わせて縮まり、境界は周囲の肌へのなじみ具合に応じて補正されます。
フェザーを含む合成後の平均色まで合わせるので、細い腕や半透明のマスクにも補正が届きます。
白飛びや黒つぶれが起きる色移動では、質感を守る範囲まで補正量が自動調整されます。

## 補正例

色ずれを模した合成画像の比較です。左から元画像、補正前、旧版、一致優先版が並んでいます。
同じ画像とマスクを、それぞれの初期設定で処理しています。
旧版の補正強度／明度補正は0.7／0.3、一致優先版は1.0／1.0です。

![元画像・補正前・旧版・一致優先版の比較](docs/demo/comparison.png)

| 合成画像のケース | 補正前の色差 | 旧版 | 一致優先版 |
| --- | ---: | ---: | ---: |
| 肌パッチ | 9.64 | 4.58 | 0.39 |
| 赤みのあるパッチ | 7.53 | 2.41 | 0.39 |
| 衣服が隣接するパッチ | 9.64 | 4.66 | 1.57 |
| 白くなったパッチ | 20.55 | 13.15 | 0.36 |
| 細いパッチ | 7.54 | 2.09 | 0.00 |

色差は元画像の対応する肌領域との平均LAB色差（Delta E76）で、小さいほど色が近いことを示します。
補正に使った参照肌との色差は、全ケースで約0.06〜0.18でした。
肌内部の細かな質感の相関は0.995以上で、コントラストの変化は約4%以内に収まっています。
マスク外は全ケースで0画素の変更、補正強度0では補正前と完全一致しています。
測定値は [metrics.json](docs/demo/metrics.json)、検証条件は [検証記録](docs/validation.md) にまとめています。

## 開発・検証

開発用のテストは、Python 3.10の独立したvenvで実行できます。
`requirements-test.txt` はこの開発環境向けの依存一覧です。

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-test.txt
python tools/fetch_forge_sources.py
python -m unittest discover -s tests -v
```

比較画像と測定値は、次のコマンドで再生成できます。

```sh
python tools/evaluate_synthetic.py --output artifacts/synthetic --baseline-ref e77dda6
```

Forgeとの連携は、Gradio 4.40.0を使用するForgeのソースに基づいています。
座標変換やフックの詳細は [Forge連携の説明](docs/forge-integration.md) を参照できます。

## ライセンス

[AGPL-3.0-only](LICENSE)で公開しています。参考プロジェクトとライセンス情報は
[NOTICE.md](NOTICE.md)に掲載しています。
