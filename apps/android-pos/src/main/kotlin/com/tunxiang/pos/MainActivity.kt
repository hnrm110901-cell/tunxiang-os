package com.tunxiang.pos

import android.os.Bundle
import android.view.View
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.tunxiang.pos.ui.navigation.NavGraph
import com.tunxiang.pos.ui.theme.TunxiangPOSTheme

/**
 * MainActivity - Single Activity hosting Compose navigation.
 *
 * Runs in fullscreen immersive mode for POS kiosk use on Sunmi T2/V2.
 * All 5 core screens + WebView fallback are managed via Compose NavGraph.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Fullscreen immersive mode for POS kiosk
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )

        setContent {
            TunxiangPOSTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    NavGraph()
                }
            }
        }
    }

    @Deprecated("Deprecated in API 33+")
    override fun onBackPressed() {
        // POS kiosk: do not allow back to exit
        // Navigation is handled within Compose
    }
}
