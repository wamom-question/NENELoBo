package main

import (
    "log"
    "fmt"
    "io"
    "net/http"
    "os"
    "strings"
    "time"
)

func main() {
    urls := []string{
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musics.json",
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musicDifficulties.json",
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musicArtists.json",
    }

    dir := "/app/assets"
    if err := os.MkdirAll(dir, os.ModePerm); err != nil {
        log.Fatalf("ディレクトリの作成に失敗しました: %v", err)
    }

    // 共通の実行ロジックを関数化して呼び出す
    runUpdateProcess := func() {
        allDownloaded := true
        for _, url := range urls {
            filename := dir + "/" + getFileName(url)
            if err := downloadJSON(url, filename); err != nil {
                log.Printf("ダウンロード失敗 (%s): %v", url, err)
                allDownloaded = false
            }
        }
        if allDownloaded {
            triggerPythonUpdate()
        }
    }

    // 1. 起動時に即時実行（これで Python 側が動き出す）
    log.Println("起動時の初回チェックを開始します...")
    runUpdateProcess()

    // 2. 定期実行ループ
    lastExecutedHour := -1
    for {
        now := time.Now().In(time.FixedZone("Asia/Tokyo", 9*60*60))
        
        // 「0分」かつ「今の一時間でまだ実行していない」場合に実行
        if now.Minute() == 0 && now.Hour() != lastExecutedHour {
            log.Printf("%d:00 の定期更新を開始します...", now.Hour())
            runUpdateProcess()
            lastExecutedHour = now.Hour()
        }
        
        time.Sleep(30 * time.Second) // 30秒ごとにチェック
    }
}

func triggerPythonUpdate() {
    // コンテナ名（song-pronu）とポートを指定
    url := "http://song-pronu:53749/update"

    // タイムアウトを設定したクライアント
    client := &http.Client{Timeout: 10 * time.Second}

    resp, err := client.Post(url, "application/json", nil)
    if err != nil {
        log.Printf("Python側への通知に失敗しました: %v", err)
        return
    }
    defer resp.Body.Close()

    if resp.StatusCode == http.StatusAccepted || resp.StatusCode == http.StatusOK {
        log.Println("Python側に更新通知を送信しました")
    } else {
        log.Printf("Python側がエラーを返しました: ステータス %d", resp.StatusCode)
    }
}

func getFileName(url string) string {
    // URLからファイル名を取得
    parts := strings.Split(url, "/")
    return parts[len(parts)-1]
}

func downloadJSON(url string, filepath string) error {
    response, err := http.Get(url)
    if err != nil {
        return err
    }
    defer response.Body.Close()

    // ステータスコードのチェック
    if response.StatusCode != http.StatusOK {
        return fmt.Errorf("ダウンロード失敗: ステータスコード %d", response.StatusCode)
    }

    file, err := os.Create(filepath)
    if err != nil {
        return err
    }
    defer file.Close()

    if _, err := io.Copy(file, response.Body); err != nil {
        return err
    }

    return nil
}
