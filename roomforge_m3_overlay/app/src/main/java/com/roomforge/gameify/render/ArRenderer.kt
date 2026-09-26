package com.roomforge.gameify.render

import android.opengl.GLES30
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.view.Surface
import com.google.ar.core.TrackingState
import com.google.ar.core.exceptions.CameraNotAvailableException
import com.roomforge.gameify.core.ScanningEngine
import com.roomforge.gameify.depth.DepthEngine
import com.roomforge.gameify.reconstruction.PlaneStructureReconstructor
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

class ArRenderer(
    private val scanningEngine: ScanningEngine,
    private val rotationProvider: () -> Int,
    private val listener: Listener
) : GLSurfaceView.Renderer {

    enum class DisplayMode { CAMERA_POINTS, DEPTH, STRUCTURE }

    interface Listener {
        fun onStats(stats: RenderStats)
        fun onRendererError(message: String)
    }

    data class RenderStats(
        val trackingState: String,
        val points: Int,
        val trackedPlanes: Int,
        val tx: Float,
        val ty: Float,
        val tz: Float,
        val depthSupported: Boolean,
        val depthWidth: Int,
        val depthHeight: Int,
        val depthValidPixels: Int,
        val depthMinMm: Int,
        val depthMaxMm: Int,
        val depthKeyframes: Int,
        val reconstructedFloors: Int,
        val reconstructedWalls: Int
    )

    private val background = CameraBackgroundRenderer()
    private val pointCloud = PointCloudRenderer()
    private val depthOverlay = DepthOverlayRenderer()
    private val depthEngine = DepthEngine()
    private val structureReconstructor = PlaneStructureReconstructor()
    private val structureRenderer = StructureRenderer()
    private var width = 1
    private var height = 1
    private var cameraTextureBoundToSession = false
    private var lastStatsNanos = 0L
    private var frameCounter = 0
    private var lastDepthSample: DepthEngine.DepthSample? = null
    private val view = FloatArray(16)
    private val projection = FloatArray(16)
    private val mvp = FloatArray(16)

    @Volatile var scanningEnabled: Boolean = true
    @Volatile var displayMode: DisplayMode = DisplayMode.CAMERA_POINTS

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        GLES30.glClearColor(0.03f, 0.04f, 0.05f, 1f)
        background.createOnGlThread()
        pointCloud.createOnGlThread()
        depthOverlay.createOnGlThread()
        structureRenderer.createOnGlThread()
        cameraTextureBoundToSession = false
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        this.width = width.coerceAtLeast(1)
        this.height = height.coerceAtLeast(1)
        GLES30.glViewport(0, 0, this.width, this.height)
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT or GLES30.GL_DEPTH_BUFFER_BIT)
        val session = scanningEngine.session ?: return
        if (scanningEngine.isPaused) return

        try {
            if (!cameraTextureBoundToSession) {
                session.setCameraTextureName(background.textureId)
                cameraTextureBoundToSession = true
            }

            val rotation = when (rotationProvider()) {
                Surface.ROTATION_90 -> Surface.ROTATION_90
                Surface.ROTATION_180 -> Surface.ROTATION_180
                Surface.ROTATION_270 -> Surface.ROTATION_270
                else -> Surface.ROTATION_0
            }
            session.setDisplayGeometry(rotation, width, height)
            val frame = session.update()
            val camera = frame.camera
            background.draw(frame)

            var pointCount = 0
            if (scanningEnabled && camera.trackingState == TrackingState.TRACKING) {
                frameCounter++
                camera.getViewMatrix(view, 0)
                camera.getProjectionMatrix(projection, 0, 0.05f, 50f)
                Matrix.multiplyMM(mvp, 0, projection, 0, view, 0)

                if (displayMode == DisplayMode.CAMERA_POINTS) {
                    frame.acquirePointCloud().use { cloud ->
                        pointCount = pointCloud.draw(cloud, mvp)
                    }
                }

                if (scanningEngine.depthSupported && frameCounter % 3 == 0) {
                    depthEngine.acquire(frame, camera.pose, allowKeyframe = true)?.let {
                        lastDepthSample = it
                    }
                }
                if (displayMode == DisplayMode.DEPTH) {
                    lastDepthSample?.let { depthOverlay.draw(frame, it) }
                }
            }

            val surfaces = if (camera.trackingState == TrackingState.TRACKING) {
                structureReconstructor.update(session)
            } else emptyList()
            if (displayMode == DisplayMode.STRUCTURE && camera.trackingState == TrackingState.TRACKING) {
                camera.getViewMatrix(view, 0)
                camera.getProjectionMatrix(projection, 0, 0.05f, 50f)
                structureRenderer.draw(surfaces, view, projection)
            }
            val reconstructedFloors = surfaces.count { it.kind == PlaneStructureReconstructor.Kind.FLOOR }
            val reconstructedWalls = surfaces.count { it.kind == PlaneStructureReconstructor.Kind.WALL }

            val now = System.nanoTime()
            if (now - lastStatsNanos > 250_000_000L) {
                lastStatsNanos = now
                val pose = camera.pose
                val trackedPlanes = session.getAllTrackables(com.google.ar.core.Plane::class.java)
                    .count { it.trackingState == TrackingState.TRACKING }
                val d = depthEngine.stats
                listener.onStats(
                    RenderStats(
                        trackingState = camera.trackingState.name,
                        points = pointCount,
                        trackedPlanes = trackedPlanes,
                        tx = pose.tx(), ty = pose.ty(), tz = pose.tz(),
                        depthSupported = scanningEngine.depthSupported,
                        depthWidth = d.width,
                        depthHeight = d.height,
                        depthValidPixels = d.validPixels,
                        depthMinMm = d.minDepthMm,
                        depthMaxMm = d.maxDepthMm,
                        depthKeyframes = d.keyframes,
                        reconstructedFloors = reconstructedFloors,
                        reconstructedWalls = reconstructedWalls
                    )
                )
            }
        } catch (e: CameraNotAvailableException) {
            listener.onRendererError("Camera became unavailable. Close other camera apps and resume scanning.")
        } catch (e: Exception) {
            listener.onRendererError("AR frame failed: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    fun resetSessionBinding() {
        cameraTextureBoundToSession = false
    }
}
