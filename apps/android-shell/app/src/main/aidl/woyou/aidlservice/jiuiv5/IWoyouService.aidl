// IWoyouService.aidl
package woyou.aidlservice.jiuiv5;

import woyou.aidlservice.jiuiv5.ICallback;

interface IWoyouService {
    void sendRAWData(in byte[] data, in ICallback callback);
    void printText(String text, in ICallback callback);
    void setFontSize(float size, in ICallback callback);
    void lineWrap(int n, in ICallback callback);
    void openDrawer(in ICallback callback);
    void cutPaper(boolean full, in ICallback callback);
}
