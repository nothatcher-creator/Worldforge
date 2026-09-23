package com.roomforge.gameify

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.opengl.GLSurfaceView
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.roomforge.gameify.ar.ArCoreScanningEngine
import com.roomforge.gameify.core.ResumeResult
import com.roomforge.gameify.render.ArRenderer

class MainActivity : Activity(), ArRenderer.Listener {
    private lateinit var glView: GLSurfaceView
    private lateinit var renderer: ArRenderer
    private lateinit var statusText: TextView
    private lateinit var guidanceText: TextView
    private lateinit var pauseButton: Button
    private lateinit var viewButton: Button
    private val scanningEngine = ArCoreScanningEngine()
    private var userPaused = false
    private var fatalErrorShown = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(9, 13, 15)
        window.navigationBarColor = Color.rgb(9, 13, 15)

        glView = GLSurfaceView(this).apply {
            setEGLContextClientVersion(3)
            preserveEGLContextOnPause = true
        }
        renderer = ArRenderer(
            scanningEngine = scanningEngine,
            rotationProvider = { windowManager.defaultDisplay.rotation },
            listener = this
        )
        glView.setRenderer(renderer)
        glView.renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY

        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        root.addView(glView, FrameLayout.LayoutParams(-1, -1))

        val topCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(10))
            setBackgroundColor(Color.argb(205, 7, 12, 14))
        }
        val title = TextView(this).apply {
            text = "ROOMFORGE · LIVE DEPTH SCAN"
            setTextColor(Color.WHITE)
            textSize = 16f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        }
        statusText = TextView(this).apply {
            text = "Starting ARCore…"
            setTextColor(Color.rgb(194, 235, 224))
            textSize = 12f
            setPadding(0, dp(4), 0, 0)
        }
        topCard.addView(title)
        topCard.addView(statusText)
        root.addView(topCard, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))

        guidanceText = TextView(this).apply {
            text = "Move slowly. RoomForge is mapping real ARCore points and depth."
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.argb(185, 7, 12, 14))
            setPadding(dp(14), dp(10), dp(14), dp(10))
            textSize = 13f
            gravity = Gravity.CENTER
        }
        val guideLp = FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM).apply {
            leftMargin = dp(12); rightMargin = dp(12); bottomMargin = dp(82)
        }
        root.addView(guidanceText, guideLp)

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(dp(8), dp(10), dp(8), dp(14))
            setBackgroundColor(Color.argb(220, 7, 12, 14))
        }
        pauseButton = Button(this).apply {
            text = "PAUSE"
            setOnClickListener { togglePause() }
        }
        viewButton = Button(this).apply {
            text = "VIEW: POINTS"
            setOnClickListener { toggleView() }
        }
        val finishButton = Button(this).apply {
            text = "FINISH"
            setOnClickListener {
                userPaused = true
                renderer.scanningEnabled = false
                pauseScanning()
                pauseButton.text = "RESUME"
                guidanceText.text = "Capture stopped. Resume to continue the same AR session."
            }
        }
        controls.addView(pauseButton, LinearLayout.LayoutParams(0, dp(54), 1f).apply { marginEnd = dp(4) })
        controls.addView(viewButton, LinearLayout.LayoutParams(0, dp(54), 1.25f).apply { marginStart = dp(4); marginEnd = dp(4) })
        controls.addView(finishButton, LinearLayout.LayoutParams(0, dp(54), 1f).apply { marginStart = dp(4) })
        root.addView(controls, FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM))

        setContentView(root)
        ensureCameraPermission()
    }

    private fun ensureCameraPermission() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), CAMERA_PERMISSION_CODE)
        }
    }

    override fun onResume() {
        super.onResume()
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED && !userPaused) {
            startOrResumeSession()
        }
    }

    override fun onPause() {
        super.onPause()
        glView.onPause()
        scanningEngine.pause()
    }

    override fun onDestroy() {
        scanningEngine.close()
        super.onDestroy()
    }

    private fun startOrResumeSession() {
        when (val result = scanningEngine.resume(this)) {
            ResumeResult.Ready -> {
                fatalErrorShown = false
                renderer.resetSessionBinding()
                renderer.scanningEnabled = true
                glView.onResume()
                guidanceText.text = if (scanningEngine.depthSupported) {
                    "Depth is active. Tap VIEW to inspect the live indoor depth map."
                } else {
                    "Depth is unavailable on this device; feature-point mapping remains active."
                }
            }
            ResumeResult.InstallRequested -> statusText.text = "Waiting for Google Play Services for AR installation…"
            is ResumeResult.Error -> showError(result.message)
        }
    }

    private fun pauseScanning() {
        glView.onPause()
        scanningEngine.pause()
    }

    private fun togglePause() {
        if (!userPaused) {
            userPaused = true
            pauseScanning()
            pauseButton.text = "RESUME"
            guidanceText.text = "Scan paused. No AR frames are being accumulated."
        } else {
            userPaused = false
            startOrResumeSession()
            pauseButton.text = "PAUSE"
        }
    }

    private fun toggleView() {
        renderer.displayMode = when (renderer.displayMode) {
            ArRenderer.DisplayMode.CAMERA_POINTS -> ArRenderer.DisplayMode.DEPTH
            ArRenderer.DisplayMode.DEPTH -> ArRenderer.DisplayMode.CAMERA_POINTS
        }
        viewButton.text = if (renderer.displayMode == ArRenderer.DisplayMode.DEPTH) "VIEW: DEPTH" else "VIEW: POINTS"
        if (renderer.displayMode == ArRenderer.DisplayMode.DEPTH && !scanningEngine.depthSupported) {
            guidanceText.text = "This phone reports ARCore Depth as unsupported; switch back to POINTS."
        }
    }

    override fun onStats(stats: ArRenderer.RenderStats) {
        runOnUiThread {
            if (fatalErrorShown) return@runOnUiThread
            statusText.text = buildString {
                append("Tracking: ${stats.trackingState}  •  Points: ${stats.points}  •  Planes: ${stats.trackedPlanes}\n")
                append("Pose m: %.2f, %.2f, %.2f".format(stats.tx, stats.ty, stats.tz))
                if (stats.depthSupported) {
                    append("  •  Depth: ${stats.depthWidth}×${stats.depthHeight}")
                    if (stats.depthValidPixels > 0) append("  ${stats.depthMinMm}-${stats.depthMaxMm}mm")
                    append("  •  KF: ${stats.depthKeyframes}")
                } else {
                    append("  •  Depth: unsupported")
                }
            }
            guidanceText.text = when (stats.trackingState) {
                "TRACKING" -> when {
                    stats.depthSupported && stats.depthValidPixels == 0 -> "Move slowly and sweep sideways so ARCore can establish depth."
                    stats.trackedPlanes == 0 -> "Tracking is good. Scan floors and walls from several angles."
                    else -> "Tracking is good. Revisit corners and furniture to strengthen depth and geometry."
                }
                "PAUSED" -> "Tracking paused. Move slower or point back toward an area already scanned."
                else -> "Tracking stopped. Resume the camera view or restart the scan."
            }
        }
    }

    override fun onRendererError(message: String) {
        runOnUiThread { showError(message) }
    }

    private fun showError(message: String) {
        fatalErrorShown = true
        statusText.text = "AR ERROR"
        guidanceText.text = message
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_PERMISSION_CODE) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startOrResumeSession()
            else showError("Camera permission is required to scan a room. Enable it in Android app settings.")
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object { private const val CAMERA_PERMISSION_CODE = 1001 }
}
