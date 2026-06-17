# 🏆 FIFA 2026 World Cup Player-Level Predictor & Simulator

這是一個結合了 **EA Sports FC 26 (FIFA 26) 全球球員級（Player-Level）數據庫**、**雙泊松期望值比分預測模型**，以及 **React 互動式對陣圖動畫網頁** 的進階預測模擬系統。

本專案擺脫了傳統單純依靠國家隊歷史勝負的 Team-Level 預測，改從每支球隊 26 人大名單的球員評分（PQS）與屬性進行底層建構。

---

## 🚀 近期重大優化與更新 (Recent Updates)

1. **實裝「非線性強弱懸殊 Domination 壓制因子」**：為解決強弱極其懸殊的對局（如葡萄牙 vs 剛果）在傳統泊松模型中「最可能比分」常被 1-0、2-0 等小比分霸佔的痛點，在 Python 模擬器與前端 React 中同步導入非線性 ELO 壓制公式。當兩隊 ELO 差大於 250 時，非線性放大強隊期望進球 $\lambda$，有效推高 3-0, 3-1, 4-0 等大比分的出現概率。
2. **重構 LLM 深度解析「批次打包 (Batching)」管線**：將原本「一場比賽呼叫一次 API」的循環架構，改成 10 場對局打包成一個 Batch 統一傳送，大幅降低每日 Gemini API Free Tier 額度消耗。
3. **實作防禦性延時與 429 重試退避 (Backoff)**：移除所有非同步併發以防 429 限制，改用序列化執行且批次間 sleep 30 秒。針對 429 錯誤加入動態重試機制，可自動解析 API 回傳的 `retryDelay`（或預設 45 秒）並重試最多 3 次。
4. **補齊缺失的真實球員身價**：針對 FC 26 官方資料庫中轉會至非歐洲主流聯賽的高齡巨星或球員（如 C 羅）身價為 0 或 NaN 的問題，設計基於球員 OVR 指級增長與年齡折損的數據科學 Fallback 估算模型，自動補齊前端顯示空白。
5. **新增「平局最可能比分 Top 3」**：重構比分過濾排序演算法，除了原有的主勝/客勝 Top 3，同步在主預測板塊、比分詳情彈窗、歷史預測對比與分享圖卡中，新增平局比分（如 `0:0`, `1:1`, `2:2`）的精準過濾與機率呈現。
6. **全新「詳細機率」統計彈窗**：在歷史預測比對區塊新增「詳細機率」快捷按鈕，可直接開啟「兩隊比數預測機率詳情」面板，細緻呈現雙方主勝、平局、客勝共 30+ 種具體比分的完整機率分布。
7. **優化 RWD 三欄響應式佈局**：將比分預測區塊從 Flex-wrap 改為全自適應網格排版，桌面端強制三欄並排且平局置中，行動端行動裝置自動向下堆疊，確保在不同解析度下皆對稱美觀。
8. **修復 Vite Fast Refresh 與熱更新 HMR**：將 `TEAM_TRANSLATIONS` 和 `toTaiwanTime` 從 `App.jsx` 抽離至獨立的 `src/utils/constants.js`。徹底解決了因混合導出造成的 `Could not Fast Refresh` 警告，將開發編譯重載（Reload）速度大幅縮短至 100ms 內。
9. **解耦「真實賽果同步」與「AI 戰力模擬」**：
   - **前端解耦雙按鈕**：新增「🔄 同步最新真實賽果」與「🤖 運行 AI 解析與戰力模擬」兩個獨立的觸發點與加載狀態。
   - **路由獨立化**：於 `vite.config.js` 分流 API。僅更新賽果時調用快速的輕量腳本；需要執行大規模模擬與調用 Gemini 深度解析時才觸發 AI 運算。
   - **已存在快取跳過 (Cache Skip) 機制**：重構 FotMob 爬蟲邏輯。針對已完賽且已有本地統計數據（stats）的歷史賽事，直接讀取快取並跳過網絡請求，解決了頻繁請求造成的 SSL 握手異常與 API 頻率限制（Rate Limit 429）問題。使日常比分同步的響應速度從原本的數十秒縮短至 **1 ~ 3 秒內**。
10. **大賽數據 MLE 擬合與防爆冷參數重構**：針對早期版本強隊勝率過高（多元共線性造成強隊通膨）的痛點，導入三大洲際盃賽真實對戰數據。利用 Python 撰寫極大似然估計腳本（`optimize_c1_c2.py`）進行 NLL 敏感度分析，成功將法國對陣塞內加爾等潛在爆冷局的獨贏勝率從 $79\%$ 校正至符合國際大盤風向的 $59\%$，大幅提升小組賽階段的爆冷預測精準度。

---

## 🔮 核心預測模型與演算法詳解 (Model & Algorithm Specifications)

本系統的預測引擎在 Python 蒙地卡羅 10,000 次模擬器與 React 前端網頁中**達成 100% 邏輯同步**。以下為預測模型的完整數學公式與演算細節：

### 1. 球員級屬性實力指標 (Player-Level PQS)

我們從 EA Sports FC 26 的全球數據庫（18,000+ 球員）中，根據 nationality 篩選球員：
- **26 人大名單篩選**：
  - **守門員**：選擇整體評分（Overall, OVR）最高的前 3 名守門員進入大名單。
  - **野戰球員**：按 Overall 降序排序，選擇前 23 名球員補齊。
  - **虛擬球員生成**：若該國真實球員人數不足 26 人（如捷克、波赫、維德角等），系統會根據該國現有真實球員的 OVR 平均值，加上隨機噪聲 $\epsilon \in [-3, 2]$ 自動生成虛擬球員補齊，其身價估值公式為：
    $$\text{Value} = \max\left(10^4, \left(\frac{\text{OVR}_{\text{final}}}{70.0}\right)^8 \times 10^6\right) \text{ EUR}$$
  - **真實球員身價 Fallback 估算**：針對 FC 26 原始數據庫中，部分效力於非歐洲主流聯賽的巨星或球員身價記為 0/NaN 的情況（如 C 羅），本系統導入基於年齡折損的 Fallback 估值公式自動補齊：
    $$\text{Value}_{\text{fallback}} = \max\left(10^4, \left(\frac{\text{OVR}}{70}\right)^{7.8} \times 10^6\right) \times \text{Age Factor} \text{ EUR}$$
    其中 $\text{Age Factor}$ 為年齡調節係數：
    * 若 $\text{Age} > 29$：$\text{Age Factor} = \max(0.05, 1.0 - (\text{Age} - 29) \times 0.12)$
    * 若 $\text{Age} < 21$：$\text{Age Factor} = 0.9 + (21 - \text{Age}) \times 0.05$
    * 其餘黃金年齡區間：$\text{Age Factor} = 1.0$

- **球員效率得分 (Player Efficiency Score)**：將球員的 100 分制 Overall 映射到 $[0.01, 0.49]$ 的實力區間：
  $$\text{Efficiency Score} = \max\left(0.01, \frac{\text{OVR} - 50}{100.0}\right)$$

- **先發評分 (Starting PQS)**：大名單前 11 人（先發陣容）的 Player Efficiency Score 平均值。
- **板凳評分 (Bench PQS)**：第 12 至第 26 名球員（替補陣容）的 Player Efficiency Score 平均值。
- **攻防拆分 PQS**：
  - **進攻評分 ($\text{att-pqs}$)**：先發陣容中，位置為 `FW` (前鋒) 或 `MF` (中場) 的球員，其 Player Efficiency Score 平均值。
  - **防守評分 ($\text{def-pqs}$)**：先發陣容中，位置為 `DF` (後衛) 或 `GK` (守門員) 的球員，其 Player Efficiency Score 平均值。

---

### 2. 賽前傷停名單排除與板凳自動遞補 (Player Injury Exclusion & Backup Rotation)

為解決大語言模型（LLM）連網抓取傷病資訊所造成的高昂 API Token 消耗，本專案直接透過純代碼爬蟲從 FotMob API 的 `matchDetails` 接口自動抓取最新名單：
- **賽前傷停採集**：每次同步真實賽果時，針對近 3 天內即將進行的未來賽事，爬蟲會解析 `content.lineup.homeTeam.unavailable` 與 `content.lineup.awayTeam.unavailable`，提取狀態為受傷（`injury`）或禁賽（`suspension`）的球員名單並寫入本地 JSON 資料庫中。
- **主力受傷剔除與板凳自動遞補**：
  當預測引擎（Python 模擬器與前端 React）讀取該國大名單時，會比對該場對局的傷兵名單：
  * 受傷球員的球員效率得分直接歸零：
    $$\text{Efficiency Score}_{\text{injured}} = 0.0$$
  * 系統會將大名單中剩下的健康球員（Active Players）重新依效率評分降序排序，由板凳中實力評分最高且位置相符的球員**自動遞補進入先發前 11 人**。
  * 重新計算後的先發攻防評分 $\text{att-pqs}_{\text{active}}$、$\text{def-pqs}_{\text{active}}$，以及受傷扣減後的替補評分 $\text{bench-pqs}_{\text{active}}$ 將直接作為本場比賽實戰數據。這會自然地折損該隊伍戰力，並考驗其板凳深度。
- **名單 UI 傷退置灰標記**：
  在「下一場比賽預測」看板會顯示傷缺名單；同時「小組國家大名單彈窗」中，若球員即將在下一場比賽缺陣，名字旁會標記紅色 `🤕 傷退` 並以 `55% 透明度（置灰）` 呈現，大幅強化了戰術真實性。

---

### 3. 動態疲勞衰減與板凳深度折損 (Dynamic Fatigue & Rotation)

在大賽中，球員體力會隨著每場比賽密集流失，影響期望實力：
- 每隊初始疲勞度 $f = 0.0$。
- 每踢完一場比賽，疲勞度累加：
  $$\Delta f = 0.04 \times (1.0 - \text{Bench PQS}) + (\text{若經歷延長賽額外 } +0.02)$$
  *板凳深度評分 (`Bench PQS`) 越佳的國家隊，每場累積疲勞的速度越慢，體現了板凳輪換的戰略價值。*
- 下一場對戰時，球隊的 PQS 與 ELO 會進行乘積折損：
  $$\text{att-pqs}_{\text{active}} = \text{att-pqs} \times (1.0 - f)$$
  $$\text{def-pqs}_{\text{active}} = \text{def-pqs} \times (1.0 - f)$$
  $$\text{ELO}_{\text{active}} = \text{FIFA-Points} \times (1.0 - f \times 0.05)$$

---

### 4. 東道主優勢 (Host Advantage)

- **東道主主場優勢 (Host Advantage)**：2026 世界盃主辦國為美、加、墨。
  - 若 Team A 是主辦國而 Team B 不是，則基礎進球期望值 $\text{Base}_A = 1.3$，$\text{Base}_B = 1.1$。
  - 若 Team B 是主辦國而 Team A 不是，則 $\text{Base}_A = 1.1$，$\text{Base}_B = 1.3$。
  - 其餘情況（雙方皆為或皆非主辦國），$\text{Base}_A = \text{Base}_B = 1.2$。

---

### 5. 進球期望值建模 (Expected Goals Specification)

為解決 ELO 積分與球員 PQS 之間的多元共線性（Multicollinearity）造成的強隊戰力通膨，本系統放棄了早期憑直覺設定的固定分母，改以三大盃賽（Euro 2024, Copa América 2024, AFCON 2025-2026）共 127 場真實大賽高階數據作為訓練集，運行**極大似然估計（MLE, Maximum Likelihood Estimation）**與負對數似然損失（NLL Loss）敏感度分析，擬合出兼顧「長期戰績基本面」與「球員級物理引擎」的**黃金權重參數（$c_1 = 0.75, c_2 = 0.20$）**：

$$\lambda = \max\left(0.2, \text{Base}_A + 0.75 \cdot \left(\frac{\text{ELO}_{A, \text{active}} - \text{ELO}_{B, \text{active}}}{400}\right) + 0.20 \cdot (\text{att-pqs}_{A, \text{active}} - \text{def-pqs}_{B, \text{active}})\right)$$

$$\mu = \max\left(0.2, \text{Base}_B - 0.75 \cdot \left(\frac{\text{ELO}_{A, \text{active}} - \text{ELO}_{B, \text{active}}}{400}\right) + 0.20 \cdot (\text{att-pqs}_{B, \text{active}} - \text{def-pqs}_{A, \text{active}})\right)$$

*註：此黃金比例既能確保 ELO 的強大預測效力，又完美保留了本系統獨創的「球員受傷、大賽疲勞、板凳遞補」等底層物理引擎的干預能力，在數學損失值（Loss）與隨機性間取得了最佳平衡。*

- **非線性強弱懸殊 (Domination) 壓制因子**：
  在實際比賽中，當強弱兩隊實力差距極度懸殊時，強隊有極高概率展現壓倒性統治力（開出 3-0, 3-1 等大比分）。為此，我們在基礎線性公式之上，加入了非線性的 ELO Domination 壓制因子：
  設 $\text{ELO}_{\text{diff}} = \text{ELO}_{A, \text{active}} - \text{ELO}_{B, \text{active}}$：
  * 當 $\text{ELO}_{\text{diff}} > 250$ 時：
    $$\lambda_{\text{final}} = \lambda + (\text{ELO}_{\text{diff}} - 250) \times 0.0018$$
    $$\mu_{\text{final}} = \max\left(0.15, \mu - (\text{ELO}_{\text{diff}} - 250) \times 0.0005\right)$$
  * 當 $\text{ELO}_{\text{diff}} < -250$ 時：
    $$\mu_{\text{final}} = \mu + (-\text{ELO}_{\text{diff}} - 250) \times 0.0018$$
    $$\lambda_{\text{final}} = \max\left(0.15, \lambda - (-\text{ELO}_{\text{diff}} - 250) \times 0.0005\right)$$
  * 其餘情況：$\lambda_{\text{final}} = \lambda$，$\mu_{\text{final}} = \mu$。
  *此修正能顯著提高強弱懸殊對局在最可能比分推薦中的大比分（如 3-0, 3-1）概率，使其更符合足球大賽實戰直覺。*

---

### 6. 雙變量泊松分佈與 Dixon-Coles 修正 (Bivariate Poisson & Dixon-Coles)

兩隊比分並非完全獨立的事件，為此本模型引入**協方差變數 $\gamma = 0.08$** 建立雙變量泊松分布。
設 $\lambda_1 = \lambda - \gamma$，$\lambda_2 = \mu - \gamma$，$\lambda_3 = \gamma$。
雙方進球為 $X=x$ 與 $Y=y$ 的未修正聯合概率為：
$$P_{\text{raw}}(X=x, Y=y) = \sum_{k=0}^{\min(x, y)} \frac{\lambda_1^{x-k} e^{-\lambda_1}}{(x-k)!} \frac{\lambda_2^{y-k} e^{-\lambda_2}}{(y-k)!} \frac{\lambda_3^k e^{-\lambda_3}}{k!}$$

由於普通泊松模型傾向於低估「低得分平局」的機率，我們使用 **Dixon-Coles 修正** 對比分矩陣進行補正（修正係數 $\rho = -0.05$）：
$$P_{\text{corrected}}(x, y) = P_{\text{raw}}(x, y) \times \tau(x, y)$$

其中修正參數 $\tau(x, y)$ 定義如下：
- 當 $x=0, y=0$：$\tau(0, 0) = 1 - \rho \lambda \mu$
- 當 $x=1, y=1$：$\tau(1, 1) = 1 - \rho$
- 當 $x=1, y=0$：$\tau(1, 0) = 1 + \rho \mu$
- 當 $x=0, y=y$：$\tau(0, 1) = 1 + \rho \lambda$
- 其它比分：$\tau(x, y) = 1.0$

---

### 7. 貝氏大盤勝率融合 (Bayesian Odds Fusion)

當系統串接並存在博弈市場的勝平負隱含賠率機率 $P_{\text{market}}(W_A)$、$P_{\text{market}}(D)$、$P_{\text{market}}(W_B)$ 時，我們採用貝氏定理進行融合：
$$P_{\text{bayes}}(x, y) = \begin{cases} 
  P_{\text{corrected}}(x, y) \times P_{\text{market}}(W_A) & \text{if } x > y \\
  P_{\text{corrected}}(x, y) \times P_{\text{market}}(D) & \text{if } x = y \\
  P_{\text{corrected}}(x, y) \times P_{\text{market}}(W_B) & \text{if } x < y 
\end{cases}$$

計算出 $P_{\text{bayes}}(x, y)$ 後，再重新進行歸一化得到最終比分機率：
$$P_{\text{final}}(x, y) = \frac{P_{\text{bayes}}(x, y)}{\sum_{u, v} P_{\text{bayes}}(u, v)}$$

加總比分概率矩陣即可得到最終的勝、平、負預測百分比，並依據 $P_{\text{final}}(x, y)$ 過濾出**主勝最可能比分 Top 3**、**平局最可能比分 Top 3** 與 **客勝最可能比分 Top 3**。

---

### 8. 即時更新 ELO 戰力指標 (Dynamic ELO Updates)

每一場完賽（不論是真實已完賽，還是在 10,000 次蒙地卡羅模擬中），都會「即時更新」雙方的 ELO 積分，模擬「爆冷氣勢崩盤」或「黑馬連勝」的動態效應：
- **世界盃決賽圈 K-Factor**：$K = 60$（最高權重係數）。
- **預期得分 (Expected Score)**：
  $$E_A = \frac{1}{10^{\frac{\text{ELO}_B - \text{ELO}_A}{400}} + 1}$$
  $$E_B = 1 - E_A$$
- **實質結果 (Actual Score)**：
  - 若 Team A 獲勝：$S_A = 1.0, S_B = 0.0$
  - 若雙方打平：$S_A = 0.5, S_B = 0.5$
  - 若 Team B 獲勝：$S_A = 0.0, S_B = 1.0$
- **ELO 更新公式**：
  $$\text{ELO}_{A, \text{new}} = \text{ELO}_A + K \times (S_A - E_A)$$
  $$\text{ELO}_{B, \text{new}} = \text{ELO}_b + K \times (S_B - E_B)$$

---

### 9. PK 大戰門將 vs 射手屬性對戰 (GK OVR vs Shooters in Penalty Shootout)

淘汰賽常規與延長賽打平後進入點球大戰，本系統捨棄了 50/50 隨機碰運氣的設計，改由屬性決定勝負：
- **守門員實力 ($GK_{\text{OVR}}$)**：提取先發陣容中 `overall` 最高者作為點球 GK，若無則預設為 60。
- **射手平均實力 ($Shoot_{\text{OVR}}$)**：提取除門將外 `overall` 前 5 高的球員平均值。
- **罰進機率**（限制在 $[0.55, 0.90]$ 區間內）：
  $$\text{rate}_A = 0.75 + \frac{\text{Shoot}_{\text{OVR}, A} - \text{GK}_{\text{OVR}, B}}{200}$$
  $$\text{rate}_B = 0.75 + \frac{\text{Shoot}_{\text{OVR}, B} - \text{GK}_{\text{OVR}, A}}{200}$$
- **模擬規則**：首輪雙方各罰 5 球。若依然平手，則進入「驟死賽（Sudden Death）」，直到分出勝負。

---

### 10. 真實數據與 FotMob API + Fallback 混合機制

- **優先採用真實數據**：系統在顯示或計算已結束比賽時，會優先檢測是否存在由 FotMob API 自動爬取寫入的高階數據（控球率、射門次數、犯規次數）。
- **Fallback 物理引擎**：若 FotMob API 數據缺失（如網路問題、超時或尚未開賽），則採用 Fallback 機制，根據雙方實力 PQS 與真實比分動態計算高階數據，防止數據寫死為 50/50：
  - **控球率計算**：
    $$\text{Possession}_A = \max\left(30, \min\left(70, 50 + (\text{avgPQS}_A - \text{avgPQS}_B) \times 100 + \text{GoalDiff} \times 2 + \epsilon\right)\right)$$
    where $\epsilon$ 為 $\pm 4\%$ 的隨機噪聲。
  - **射門次數與犯規次數**：基於控球比例與進球數進行隨機泊松抽樣生成，完美還原場上的攻防情境。

---

## 💡 數據演進與研發心路歷程 (Data Evolution & Rationale)

在專案開發過程中，我們曾經歷了關鍵的數據選取變革：

### 🚫 聯賽真實統計數據的困境
在初期，我們嘗試使用球員在俱樂部聯賽的歷史統計（如賽季進球、助攻、傳球）。但這帶來兩個無法克服的痛點：
1. **中下游國家隊數據殘缺**：如捷克、波赫、維德角等隊伍的球員散落於全球二三線聯賽，面臨嚴重的數據缺失。之前版本被迫使我們在小組賽中採用「輪空判負 (0:3)」的生硬邏輯 bypass，破壞了 48 強賽程的完整性。
2. **跨聯盟比較偏誤**：不同國家的球員在完全不同的聯盟與賽制中踢球（如英超 vs 日職聯）。各聯賽的競技強度不同，無法公允地把「日職聯進 15 球的前鋒」與「英超進 10 球的前鋒」放在同一個基準線上對比。

### 💡 轉向官方遊戲數據 (EA Sports FC 26)
為了獲得公允的全球球員基準線，我們改用最新的 **EA Sports FC 26 資料庫**：
- **標準化全球評級**：EA 擁有龐大的全球球探體系，使用同一套標準（Overall, Attributes）對 18,000+ 球員進行全方位定性與定量評分，提供了唯一可行的**公允基準線**。
- **解鎖 48 強全陣容**：基於最新的 FC 26 數據，我們完整補齊了 48 支參賽隊伍的所有大名單，**100% 還原真實世界 Wikipedia 抽籤分組**，並完全移除了輪空判負的代碼！

---

## 📂 專案目錄結構

- `backend/`
  - `FC26_20250921.csv` - 最新版 EA Sports FC 26 全球球員數據庫 (核心數據)
  - `generate_frontend_data.py` - 前端數據生成器 (解析 CSV 並產生 `teams_db.json`)
  - `optimize_c1_c2.py` - 基於真實大賽數據的極大似然估計（MLE）與損失函數敏感度分析腳本 (演算法調校核心)
  - `player_level_simulator.py` - Python 蒙地卡羅 10,000 次模擬器核心
  - `sync_real_games.py` - FotMob 真實數據同步爬蟲管線
- `frontend/`
  - `src/App.jsx` - React 前端核心邏輯與對陣圖 UI 渲染
  - `src/components/NextMatchPredictor.jsx` - 下一場比賽超級預測器與比數 Modal
  - `src/utils/poissonMath.js` - 雙變量泊松與 Dixon-Coles 修正前端計算庫
  - `src/utils/simulator.js` - 前端預測模擬引擎 (與 Python 100% 邏輯同步)
  - `src/utils/constants.js` - 國家中文對照表與時間轉換工具庫 (解決 HMR 衝突)
  - `src/teams_db.json` - 包含 48 隊 26 人大名單 of JSON 數據庫
  - `src/real_games_results.json` - 真實世界比賽結果與高階數據

---

## 🚀 快速開始 (Quick Start)

### 1. 數據與模擬驗證
於根目錄下執行：
```bash
# 1. 重新生成前端所需 JSON 資料庫
python3 backend/generate_frontend_data.py

# 2. 執行 Python 10,000 次蒙地卡羅模擬
python3 backend/player_level_simulator.py
```

### 2. 啟動 React 前端對陣圖網頁
於 `frontend` 目錄下執行：
```bash
cd frontend
npm install
npm run dev
```
啟動後在瀏覽器開啟 `http://localhost:5173/` (或對應埠口) 即可體驗高互動性的 2026 世界盃動畫對陣圖與球員大名單面板！
