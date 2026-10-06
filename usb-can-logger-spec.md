# USB-CAN Bus Logger 專案開發規格書暨實作指南

> 本文件由 PDF「Python 控制 USB-CAN 紀錄程式」（Gemini 對話匯出，6 頁）整理而成，供 coding agent 作為開發依據。
> - 第 1–6 章為原文內容（已修復 PDF 文字擷取造成的錯位與斷行，程式碼縮排依原文規定統一為 2 個空白）。
> - 附錄 A 為原文的單檔原型程式。
> - 附錄 B 為「原文未提、轉換時發現的問題與建議」，**非原文內容**，請 coding agent 實作時一併處理或與專案負責人確認。
> - 原 PDF 中的 USB-CAN 適配器照片未包含於 PDF，無法轉出。

## 1. 專案概述 (Project Overview)

本專案旨在開發一個基於 Python 的自動化 CAN Bus 資料記錄器，透過創芯科技 (Chuangxin Technology) USB-CAN 雙路適配器（型號基於周立功 USBCAN-2C / CANalyst-II 架構）擷取 CAN Bus 網路上的封包。系統支援長時間連續監聽，並具備按小時自動分割記錄檔 (`.csv`) 的功能，方便後續分析與管理。

### 1.1 功能需求摘要

| 項目 | 需求 |
| --- | --- |
| 擷取來源 | USB-CAN 適配器（預設使用 CAN1 / 通道 0） |
| 記錄內容 | 時間戳、CAN ID、幀類型（STD/EXT）、資料長度、資料內容（Hex） |
| 儲存格式 | `.csv`（UTF-8） |
| 檔案切分 | **每小時產生一個新檔案**，供長時間記錄使用 |
| 檔名規範 | `can_log_YYYYMMDD_HH0000.csv`，例如 `can_log_20261006_080000.csv` |
| 停止方式 | `Ctrl+C`，需安全關閉檔案與設備 |

## 2. 系統架構與環境需求 (System Architecture & Requirements)

### 2.1 硬體規格與接線 (Hardware)

- **適配器型號**：創芯科技 USB-CAN 適配器（雙通道 CAN1 / CAN2）
- **接線說明**：
  - `CANH` / `CANL`：分別連接至測試目標 CAN 網路之 CAN_H 與 CAN_L。
  - **120Ω 終端電阻**：若適配器位於 CAN 匯流排末端，請將 120Ω `R+` 短接至 `CANH`、`R-` 短接至 `CANL`，以啟用內部匹配電阻。

### 2.2 軟體與執行環境 (Software Environment)

- **作業系統**：Windows 10 / 11 (64-bit)
- **程式語言**：Python 3.8+（64-bit 或 32-bit，需與 C 語言 DLL 之位元數一致）
- **依賴動態庫**：`ControlCAN.dll` 及相關系統驅動（如 `kerneldlls` 目錄，隨廠牌驅動光碟或 SDK 提供）
- **Python 核心模組**：`ctypes`, `threading`, `datetime`, `os`, `time`, `logging`

## 3. 專案目錄結構 (Directory Structure)

```text
can_logger_project/
├── drivers/
│   ├── ControlCAN.dll         # 創芯/周立功提供的 CAN 控制 DLL
│   └── kerneldlls/            # 驅動附帶的依賴資料夾（若有）
├── logs/                      # 自動生成的 CSV 日誌輸出資料夾
│   └── can_log_20261006_080000.csv
├── src/
│   ├── __init__.py
│   ├── can_adapter.py         # Ctypes 封裝 ControlCAN API 與資料結構
│   └── logger_service.py      # 主邏輯：按時分割檔案與背景接收執行緒
├── main.py                    # 專案程式入口點
└── README.md                  # 說明文件
```

## 4. 核心模組實作 (Implementation)

在 Python 中，所有縮排皆嚴格遵守 **2 個空白**。

### 4.1 CAN 動態庫封裝 (`src/can_adapter.py`)

```python
import ctypes
from ctypes import Structure, c_uint, c_ubyte, c_ushort, c_byte, POINTER

# 1. 定義 ControlCAN 結構體
class VCI_INIT_CONFIG(Structure):
  _fields_ = [
    ("AccCode", c_uint),     # 驗收碼
    ("AccMask", c_uint),     # 屏蔽碼
    ("Reserved", c_uint),    # 保留
    ("Filter", c_ubyte),     # 濾波方式 (0: 雙濾波, 1: 單濾波)
    ("Timing0", c_ubyte),    # 波特率定時器 0
    ("Timing1", c_ubyte),    # 波特率定時器 1
    ("Mode", c_ubyte)        # 模式 (0: 正常, 1: 只聽, 2: 自測)
  ]

class VCI_CAN_OBJ(Structure):
  _fields_ = [
    ("ID", c_uint),          # CAN ID
    ("TimeStamp", c_uint),   # 時間戳 (32位元微秒)
    ("TimeFlag", c_ubyte),   # 是否使用時間戳
    ("SendType", c_ubyte),   # 發送類型
    ("RemoteFlag", c_ubyte), # 0: 資料幀, 1: 遠程幀
    ("ExternFlag", c_ubyte), # 0: 標準幀, 1: 擴展幀
    ("DataLen", c_ubyte),    # 資料長度 (0~8)
    ("Data", c_ubyte * 8),   # 資料內容
    ("Reserved", c_ubyte * 3) # 保留
  ]

class CANAdapter:
  def __init__(self, dll_path="./drivers/ControlCAN.dll", dev_type=4, dev_index=0):
    self.dev_type = dev_type
    self.dev_index = dev_index
    self.dll = ctypes.windll.LoadLibrary(dll_path)

  def open_device(self):
    return self.dll.VCI_OpenDevice(self.dev_type, self.dev_index, 0) == 1

  def init_can(self, can_index=0, timing0=0x00, timing1=0x1C):
    # 預設波特率為 500Kbps (Timing0=0x00, Timing1=0x1C)
    config = VCI_INIT_CONFIG()
    config.AccCode = 0x00000000
    config.AccMask = 0xFFFFFFFF
    config.Filter = 1
    config.Timing0 = timing0
    config.Timing1 = timing1
    config.Mode = 0

    if self.dll.VCI_InitCAN(self.dev_type, self.dev_index, can_index, ctypes.byref(config)) != 1:
      return False
    return self.dll.VCI_StartCAN(self.dev_type, self.dev_index, can_index) == 1

  def receive(self, can_index=0, buffer_size=2000, wait_time=100):
    rx_buffer = (VCI_CAN_OBJ * buffer_size)()
    count = self.dll.VCI_Receive(
      self.dev_type, self.dev_index, can_index, ctypes.byref(rx_buffer), buffer_size, wait_time
    )
    results = []
    for i in range(count):
      results.append(rx_buffer[i])
    return results

  def close_device(self):
    self.dll.VCI_CloseDevice(self.dev_type, self.dev_index)
```

### 4.2 自動按時切換檔案與接收服務 (`src/logger_service.py`)

```python
import os
import time
import threading
from datetime import datetime
from src.can_adapter import CANAdapter

class HourlyCANLogger:
  def __init__(self, can_adapter, can_index=0, output_dir="./logs"):
    self.adapter = can_adapter
    self.can_index = can_index
    self.output_dir = output_dir
    self.is_running = False
    self.current_hour_str = ""
    self.current_file = None

    if not os.path.exists(self.output_dir):
      os.makedirs(self.output_dir)

  def _get_file_handle(self):
    now = datetime.now()
    hour_str = now.strftime("%Y%m%d_%H")

    # 跨小時切換檔案
    if hour_str != self.current_hour_str:
      if self.current_file:
        self.current_file.close()

      self.current_hour_str = hour_str
      filename = f"can_log_{hour_str}0000.csv"
      filepath = os.path.join(self.output_dir, filename)

      file_exists = os.path.exists(filepath)
      self.current_file = open(filepath, "a", encoding="utf-8", buffering=1) # 行緩衝寫入
      if not file_exists:
        # 寫入 CSV 標頭
        self.current_file.write("Timestamp,CAN_ID,Frame_Type,Data_Length,Data_Hex\n")

    return self.current_file

  def start_logging(self):
    self.is_running = True
    self.worker_thread = threading.Thread(target=self._log_loop, daemon=True)
    self.worker_thread.start()

  def _log_loop(self):
    while self.is_running:
      messages = self.adapter.receive(can_index=self.can_index)
      if messages:
        f = self._get_file_handle()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        lines = []
        for msg in messages:
          can_id = f"0x{msg.ID:08X}" if msg.ExternFlag else f"0x{msg.ID:03X}"
          frame_type = "EXT" if msg.ExternFlag else "STD"
          data_bytes = [f"{msg.Data[j]:02X}" for j in range(msg.DataLen)]
          data_hex = " ".join(data_bytes)
          lines.append(f"{now_str},{can_id},{frame_type},{msg.DataLen},{data_hex}\n")

        f.writelines(lines)
      else:
        time.sleep(0.005) # 無資料時讓出 CPU 資源

  def stop_logging(self):
    self.is_running = False
    if self.worker_thread.is_alive():
      self.worker_thread.join()
    if self.current_file:
      self.current_file.close()
      self.current_file = None
```

### 4.3 專案程式入口點 (`main.py`)

```python
import time
import sys
from src.can_adapter import CANAdapter
from src.logger_service import HourlyCANLogger

def main():
  print("=== USB-CAN 長時間日誌紀錄服務啟動 ===")
  # 初始化 CAN 適配器
  adapter = CANAdapter(dll_path="./drivers/ControlCAN.dll")
  if not adapter.open_device():
    print("錯誤：無法開啟 CAN 設備，請檢查 USB 連接與驅動程式。")
    sys.exit(1)

  # 設定波特率 500Kbps 並初始化 CAN1 (通道 0)
  if not adapter.init_can(can_index=0, timing0=0x00, timing1=0x1C):
    print("錯誤：初始化 CAN 通道失敗。")
    adapter.close_device()
    sys.exit(1)

  print("CAN 通道開啟成功，正在準備紀錄服務...")
  logger = HourlyCANLogger(adapter=adapter, can_index=0, output_dir="./logs")

  try:
    logger.start_logging()
    print("記錄服務運作中 (按下 Ctrl+C 停止記錄)...")
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    print("\n接收到使用者停止指令，正在安全關閉日誌檔案與設備...")
  finally:
    logger.stop_logging()
    adapter.close_device()
    print("系統已安全停止。")

if __name__ == "__main__":
  main()
```

> 備註：原文 `can_adapter.py` 的 `c_ushort`、`c_byte`、`POINTER` 匯入未被使用，保留原樣，可自行清理。

## 5. CSV 資料格式說明 (CSV Output Format)

每個生成的 `.csv` 檔案格式如下（UTF-8，首列為標頭）：

| Timestamp（時間戳） | CAN_ID（封包 ID） | Frame_Type（幀類型） | Data_Length（長度） | Data_Hex（資料內容） |
| --- | --- | --- | --- | --- |
| 2026-10-06 08:00:01.123 | 0x00000123 | STD | 8 | 11 22 33 44 55 66 77 88 |
| 2026-10-06 08:00:01.125 | 0x18FEF100 | EXT | 8 | 00 FF 00 00 00 00 00 00 |

- 標頭：`Timestamp,CAN_ID,Frame_Type,Data_Length,Data_Hex`
- 檔名規範：`can_log_YYYYMMDD_HH0000.csv`（例如 `can_log_20261006_080000.csv`），每小時自動切換並建立新檔案。
- 備註：原文範例表列 STD 幀的 ID 顯示為 `0x00000123`（8 位十六進位），但原文程式碼對 STD 幀實際輸出 3 位格式 `0x123`（EXT 才輸出 8 位）。以程式碼為準；若要統一格式請見附錄 B。

## 6. 測試與維護注意事項 (Maintenance & Verification)

1. **Python 位元版本對齊**：創芯科技 / 周立功 SDK 的 `ControlCAN.dll` 常見有 32-bit 與 64-bit 版本。請務必確保執行的 Python 環境與 `ControlCAN.dll` 位元數匹配，否則 ctypes 載入時會報出 `OSError: [WinError 193]`。
2. **記憶體與長時運作穩定性**：寫入檔案使用 `buffering=1`（行緩衝）及 `writelines()` 批次寫入，可減少磁碟 I/O 損耗並避免長時間執行時記憶體累積。
3. **終端匹配電阻確認**：在高速 CAN 網路（如 500Kbps / 1Mbps）下，若出現大量物理層錯誤或無法接收，請檢查是否需短接 120Ω 終端電阻。

### 6.1 常見配置說明（原文）

**波特率 (Baud Rate) 參數**（原文）：

| 波特率 | Timing0 | Timing1 |
| --- | --- | --- |
| 500 Kbps | `0x00` | `0x1C` |
| 250 Kbps | `0x01` | `0x1C` |
| 125 Kbps | `0x01`（原文如此，疑有誤，見附錄 B-1） | `0x1C`（原文註：搭配預分頻設定，或參考官方驅動對應表的暫存器設定） |

**裝置參數**（原文原型程式）：`DEV_USBCAN2 = 4`（周立功 / 創芯常用 USBCAN-2C 或 CANalyst-II 設備型號通常為 4）、`DEV_INDEX = 0`（第 1 台設備）、`CAN_INDEX = 0`（0: CAN1, 1: CAN2）。

---

## 附錄 A：原文單檔原型程式（僅供參考）

原文第一個回覆提供的單檔版本（固定錄製 `duration_sec` 秒、單一 CSV）。正式開發請以第 4 章模組化版本為準。

```python
import ctypes
import time
from ctypes import Structure, c_uint, c_ubyte, c_ushort, c_byte

# 1. 定義 ControlCAN 相關結構體
class VCI_INIT_CONFIG(Structure):
  _fields_ = [
    ("AccCode", c_uint),     # 驗收碼
    ("AccMask", c_uint),     # 屏蔽碼
    ("Reserved", c_uint),    # 保留
    ("Filter", c_ubyte),     # 濾波方式 (0: 雙濾波, 1: 單濾波)
    ("Timing0", c_ubyte),    # 波特率定時器 0
    ("Timing1", c_ubyte),    # 波特率定時器 1
    ("Mode", c_ubyte)        # 模式 (0: 正常, 1: 只聽, 2: 自測)
  ]

class VCI_CAN_OBJ(Structure):
  _fields_ = [
    ("ID", c_uint),          # CAN ID
    ("TimeStamp", c_uint),   # 時間戳
    ("TimeFlag", c_ubyte),   # 是否使用時間戳
    ("SendType", c_ubyte),   # 發送類型
    ("RemoteFlag", c_ubyte), # 0: 資料幀, 1: 遠程幀
    ("ExternFlag", c_ubyte), # 0: 標準幀, 1: 擴展幀
    ("DataLen", c_ubyte),    # 資料長度 (0~8)
    ("Data", c_ubyte * 8),   # 資料內容
    ("Reserved", c_ubyte * 3) # 保留
  ]

# 2. 載入 DLL (請替換為你的 ControlCAN.dll 路徑)
can_dll = ctypes.windll.LoadLibrary("./ControlCAN.dll")

# 定義設備類型 (周立功/創芯常用的 USBCAN-2C 或 CANalyst-II 設備型號通常為 4)
DEV_USBCAN2 = 4
DEV_INDEX = 0 # 設備索引號 (第1台設備)
CAN_INDEX = 0 # 通道索引號 (0: CAN1, 1: CAN2)

# 3. 開啟與初始化設備
def init_can():
  # 開啟設備
  if can_dll.VCI_OpenDevice(DEV_USBCAN2, DEV_INDEX, 0) != 1:
    print("開啟 CAN 設備失敗！")
    return False

  # 設定波特率：500 Kbps (Timing0=0x00, Timing1=0x1C)
  # 若為 250 Kbps 請設定 Timing0=0x01, Timing1=0x1C
  config = VCI_INIT_CONFIG()
  config.AccCode = 0x00000000
  config.AccMask = 0xFFFFFFFF
  config.Filter = 1
  config.Timing0 = 0x00
  config.Timing1 = 0x1C
  config.Mode = 0 # 正常模式

  # 初始化 CAN1
  if can_dll.VCI_InitCAN(DEV_USBCAN2, DEV_INDEX, CAN_INDEX, ctypes.byref(config)) != 1:
    print("初始化 CAN 通道失敗！")
    can_dll.VCI_CloseDevice(DEV_USBCAN2, DEV_INDEX)
    return False

  # 啟動 CAN1
  if can_dll.VCI_StartCAN(DEV_USBCAN2, DEV_INDEX, CAN_INDEX) != 1:
    print("啟動 CAN 通道失敗！")
    can_dll.VCI_CloseDevice(DEV_USBCAN2, DEV_INDEX)
    return False
  print("CAN 設備啟動成功，開始監聽...")
  return True

# 4. 讀取並記錄封包
def start_logging(log_filename="can_log.csv", duration_sec=10):
  rx_vci_obj = (VCI_CAN_OBJ * 2000)() # 建立接收緩衝區
  with open(log_filename, "w", encoding="utf-8") as f:
    f.write("Timestamp,CAN_ID,Frame_Type,Data_Length,Data(Hex)\n")

    start_time = time.time()
    try:
      while time.time() - start_time < duration_sec:
        # VCI_Receive(DevType, DevIndex, CANIndex, pReceive, Len, WaitTime)
        count = can_dll.VCI_Receive(DEV_USBCAN2, DEV_INDEX, CAN_INDEX, ctypes.byref(rx_vci_obj), 2000, 100)

        if count > 0:
          for i in range(count):
            msg = rx_vci_obj[i]
            timestamp = f"{time.time():.4f}"
            can_id = hex(msg.ID)
            frame_type = "EXT" if msg.ExternFlag else "STD"
            data_hex = " ".join([f"{msg.Data[j]:02X}" for j in range(msg.DataLen)])

            # 印出並寫入 CSV
            log_line = f"{timestamp},{can_id},{frame_type},{msg.DataLen},{data_hex}"
            print(f"收到封包: {log_line}")
            f.write(f"{log_line}\n")

        time.sleep(0.01) # 短暫休眠避免 CPU 使用率過高
    except KeyboardInterrupt:
      print("使用者中斷紀錄。")
    finally:
      # 關閉設備
      can_dll.VCI_CloseDevice(DEV_USBCAN2, DEV_INDEX)
      print("CAN 設備已關閉，日誌已儲存。")

if __name__ == "__main__":
  if init_can():
    start_logging(log_filename="can_bus_data.csv", duration_sec=30)
```

---

## 附錄 B：轉換時發現的問題與建議（非原文，請 coding agent 處理或向負責人確認）

> 以下為轉換者依一般 ControlCAN / CAN Bus 知識所做的檢視。標示「需實機／SDK 文件驗證」者，不要直接當作定論。

1. **125 Kbps 的 Timing 值疑有誤**：原文 125K 與 250K 同為 `Timing0=0x01, Timing1=0x1C`，不可能同時正確。常見 ZLG ControlCAN 對照表為 125K＝`0x03 / 0x1C`（其他：1M＝`0x00 / 0x14`、500K＝`0x00 / 0x1C`、250K＝`0x01 / 0x1C`、100K＝`0x04 / 0x1C`、50K＝`0x09 / 0x1C`）。**需對照創芯 SDK 文件並以實機驗證**後再寫入程式；建議做成可由設定檔／參數指定波特率，而非寫死 500K。
2. **Mode=0（正常模式）會在匯流排上回應 ACK**：若僅是被動監聽既有網路（例如不希望影響待測系統），建議評估使用 `Mode=1`（只聽模式，原文結構註解已列出）。是否採用取決於該 CAN 網路是否需要本適配器充當 ACK 節點。
3. **時間戳精度**：原文使用 PC 端 `datetime.now()`，且同一次 `VCI_Receive` 批次內的所有封包共用同一個時間字串（毫秒），不反映實際到達時間。若需精確時序分析，可評估啟用硬體時間戳（`VCI_CAN_OBJ.TimeFlag` / `TimeStamp`；單位與基準需對照 SDK 文件，原文註解為「32 位元微秒」，需驗證）並新增一欄寫入 CSV。
4. **只記錄 CAN1**：`main.py` 固定 `can_index=0`；適配器為雙通道，若需同時記錄 CAN2，需另開 `init_can(can_index=1)` 與第二個 logger，並在 CSV 增加通道欄位。
5. **未區分遠端幀**：`RemoteFlag` 讀進來但未寫入 CSV，遠端幀會被記成資料長度為 0 或帶資料的普通行。若需完整記錄，建議在 CSV 增加 `Remote` 欄位或以 `Frame_Type` 區分。
6. **STD ID 格式不一致**：5 章範例表顯示 `0x00000123`，程式碼實際輸出 `0x123`。建議統一（例如一律 8 位）以利後續解析。
7. **切檔邏輯只在有資料時觸發**：`_get_file_handle()` 只在收到封包時呼叫，整個小時無封包則不會產生該小時的檔案；若需要「每小時必有檔案」，需另行處理。檔案與標頭也是以 append 模式開啟，程式重啟於同一小時會接續寫入同一檔（標頭只在檔案不存在時寫入，此行為合理，但請在測試中確認）。
8. **錯誤處理與日誌**：`threading` 背景執行緒內若 `VCI_Receive` 回傳負值或例外（USB 拔除等），目前沒有處理，執行緒可能靜默失敗。建議增加例外捕捉、`logging` 記錄與自動重連；`VCI_Receive` 回傳 `0xFFFFFFFF`（-1）表示錯誤，需對照 SDK 文件確認。
9. **每輪迴圈重新配置 2000 筆接收緩衝**（`receive()`）：長時間運行會有不必要的記憶體配置，可改為於建構時配置一次並重用。
10. **平台限制**：`ctypes.windll` 僅限 Windows。若日後需跨平台，可評估 `python-can` 的 `canalystii` 介面（以 libusb 直接驅動 CANalyst-II 類裝置，不需 `ControlCAN.dll`）；是否相容本適配器需實機驗證。
11. **部署前提**：目前方案需 `ControlCAN.dll`（廠商驅動）與 Windows，可離線／地端運作，不依賴任何雲端服務。
