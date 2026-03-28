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

    // ディレクトリの作成
    dir := "/app/assets"
    if err := os.MkdirAll(dir, os.ModePerm); err != nil {
        log.Fatalf("ディレクトリの作成に失敗しました: %v", err)
    }

    for _, url := range urls {
        filename := dir + "/" + getFileName(url) // フルパスを指定
        if err := downloadJSON(url, filename); err != nil {
            log.Printf("初回ダウンロード失敗: %v", err)
        }
    }

    for {
            now := time.Now().In(time.FixedZone("Asia/Tokyo", 9*60*60))
            if now.Minute() == 0 {
                allDownloaded := true
                for _, url := range urls {
                    filename := dir + "/" + getFileName(url)
                    if err := downloadJSON(url, filename); err != nil {
                        log.Printf("ダウンロード失敗 (%s): %v", url, err)
                        allDownloaded = false // 1つでも失敗したらフラグを倒す
                    }
                }

                // 全ファイルのダウンロード試行が終わったタイミングで通知
                // (少なくとも 1 時間に 1 回、全ファイルを最新にした状態で Python を動かす)
                if allDownloaded {
                    triggerPythonUpdate()
                }

                time.Sleep(time.Hour)
            } else {
                time.Sleep(time.Minute)
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
