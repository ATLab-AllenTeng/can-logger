# USB-CAN Bus Logger

Windows 上使用創芯科技、周立功 ControlCAN 相容 USB-CAN 轉接器的長時間 CAN Bus 記錄工具。程式會接收單一 CAN 通道資料，並依本機時間每小時輸出一個 UTF-8 CSV 檔。

## 功能

- 支援 ControlCAN 相容的 USB-CAN 雙通道裝置，預設記錄 CAN1。
- 預設 500 Kbps，並可從命令列選擇常見速率或直接覆寫 Timing 暫存器值。
- 預設採用只聽模式，避免對既有匯流排回覆 ACK。必要時可改成正常模式。
- 每小時產生 `can_log_YYYYMMDD_HH0000.csv`，程序重啟於同一小時時會接續寫入同一檔案。
- 即使整個小時沒有流量，持續運行中的服務也會建立該小時的空 CSV 與標頭。
- 以背景接收執行緒記錄資料，將裝置錯誤回傳至主程序，並在 Ctrl+C 時關閉檔案與設備。
- 僅使用 Python 標準函式庫。測試無須 USB-CAN 硬體或 DLL。

## 需求

- Windows 10 或 Windows 11。
- Python 3.8 或更新版本。
- 供應商提供的 `ControlCAN.dll` 與其相依 DLL。
- Python 與 `ControlCAN.dll` 必須同為 32 位元或同為 64 位元。

已驗證的 `drivers/ControlCAN.dll` 會隨專案版本控制。其他供應商相依 DLL 預設仍不會加入 Git，除非已確認其授權允許散布且專案明確需要。

## 安裝與啟動

將供應商提供的檔案放在下列位置：

```text
drivers/
├── ControlCAN.dll
└── kerneldlls/                 # 供應商另外提供的相依 DLL，如需要
```

建立虛擬環境並執行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python main.py
```

預設會以 CAN1、500 Kbps、裝置類型 `4`、裝置索引 `0` 與只聽模式記錄至 `logs/`。按 Ctrl+C 會安全停止。

## 常用設定

```powershell
# 記錄 CAN2，速率為 250 Kbps
python main.py --channel 1 --bitrate 250k

# 指定 DLL 與輸出目錄
python main.py --dll C:\vendor\ControlCAN.dll --output-dir D:\can-logs

# 若此轉接器必須在匯流排上 ACK，改用正常模式
python main.py --normal-mode

# 使用供應商 SDK 驗證過的 Timing 值覆寫預設值
python main.py --timing0 0x03 --timing1 0x1C

# 顯示詳細執行紀錄
python main.py --verbose
```

速率預設值來自常見 ZLG ControlCAN 對照表：

| 速率 | Timing0 | Timing1 |
| --- | --- | --- |
| 1 Mbps | `0x00` | `0x14` |
| 500 Kbps | `0x00` | `0x1C` |
| 250 Kbps | `0x01` | `0x1C` |
| 125 Kbps | `0x03` | `0x1C` |
| 100 Kbps | `0x04` | `0x1C` |
| 50 Kbps | `0x09` | `0x1C` |

供應商 SDK、晶振與裝置韌體可能不同。尤其是 125 Kbps，必須先依實機與供應商文件確認，再用於正式量測。

## CSV 格式

檔案採 UTF-8 且使用下列標頭：

```csv
Timestamp,CAN_ID,Frame_Type,Data_Length,Data_Hex
2026-10-06 08:00:01.123,0x123,STD,8,11 22 33 44 55 66 77 88
2026-10-06 08:00:01.125,0x18FEF100,EXT,8,00 FF 00 00 00 00 00 00
```

標準幀 ID 使用三位十六進位格式，擴展幀使用八位格式，與規格的參考程式一致。遠端幀以 `STD_RTR` 或 `EXT_RTR` 寫入 `Frame_Type`，並保持資料欄空白，因此不會與資料幀混淆。

`Timestamp` 是程式從 DLL 收到每一幀時建立的本機時間。原始硬體時間戳仍保留在程式模型內，但尚未輸出為 CSV 欄位，因為其單位和基準必須先由供應商 SDK 驗證。

## 驗證

在未連接硬體的開發環境中執行：

```powershell
python -m unittest discover -s tests -v
```

實機驗收前請依序確認：

1. Python 與 DLL 位元數相符，並可開啟設備。
2. CANH、CANL 與終端電阻配置符合匯流排拓撲。
3. 使用已知流量與 SDK 文件確認實際通道、設備類型與位元率。
4. 驗證只聽模式是否符合測試網路需求。若匯流排需要此裝置 ACK，才使用 `--normal-mode`。
5. 跨整點持續記錄，確認檔名、CSV 標頭、資料完整性與停止流程。

## 專案結構

```text
.
├── drivers/                    # 供應商 DLL 放置位置，不納入版本控制
├── logs/                       # 自動生成 CSV 輸出
├── src/
│   ├── can_adapter.py           # ControlCAN ctypes 封裝與資料接收
│   ├── logger_service.py        # 背景接收與每小時 CSV 輪替
│   └── models.py                # CAN 資料模型與 CSV 格式化
├── tests/                       # 不需硬體的單元測試
├── DEVELOPMENT_PLAN.md          # 分階段開發與驗收計畫
└── main.py                      # 命令列進入點
```

## 已知限制

- 目前僅初始化並記錄一個通道。雙通道同步記錄與通道欄位屬後續擴充。
- DLL 載入與實機接收僅支援 Windows。
- USB 裝置拔除或 SDK 呼叫錯誤會結束記錄並留下錯誤日誌。自動重連需要針對實際 SDK 回傳碼與設備行為驗證後再加入。
