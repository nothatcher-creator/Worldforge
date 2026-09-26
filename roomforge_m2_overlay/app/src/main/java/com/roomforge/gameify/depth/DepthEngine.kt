package com.roomforge.gameify.depth

import com.google.ar.core.Frame
import com.google.ar.core.Pose
import com.google.ar.core.exceptions.NotYetAvailableException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.ArrayDeque

/**
 * Acquires real ARCore automatic depth and keeps a bounded in-memory keyframe cache.
 * No depth data is uploaded or permanently written to disk in this milestone.
 */
class DepthEngine(
    private val maxKeyframes: Int = 30,
    private val keyframeIntervalNanos: Long = 1_000_000_000L
) {
    data class DepthSample(
        val timestampNanos: Long,
        val width: Int,
        val height: Int,
        val previewR8: ByteBuffer,
        val packedDepthMm: ByteArray,
        val validPixels: Int,
        val minDepthMm: Int,
        val maxDepthMm: Int,
        val pose: FloatArray
    )

    data class Stats(
        val width: Int = 0,
        val height: Int = 0,
        val validPixels: Int = 0,
        val minDepthMm: Int = 0,
        val maxDepthMm: Int = 0,
        val keyframes: Int = 0
    )

    private val keyframes = ArrayDeque<DepthSample>()
    private var lastKeyframeNanos = 0L

    @Volatile
    var stats: Stats = Stats()
        private set

    fun acquire(frame: Frame, cameraPose: Pose, allowKeyframe: Boolean): DepthSample? {
        return try {
            frame.acquireDepthImage16Bits().use { image ->
                val width = image.width
                val height = image.height
                val plane = image.planes[0]
                val src = plane.buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
                val rowStride = plane.rowStride
                val pixelStride = plane.pixelStride
                val packed = ByteArray(width * height * 2)
                val preview = ByteBuffer.allocateDirect(width * height).order(ByteOrder.nativeOrder())

                var valid = 0
                var minMm = Int.MAX_VALUE
                var maxMm = 0
                var outByte = 0
                for (y in 0 until height) {
                    val rowStart = y * rowStride
                    for (x in 0 until width) {
                        val srcOffset = rowStart + x * pixelStride
                        val mm = src.getShort(srcOffset).toInt() and 0xFFFF
                        packed[outByte++] = (mm and 0xFF).toByte()
                        packed[outByte++] = ((mm ushr 8) and 0xFF).toByte()
                        if (mm > 0) {
                            valid++
                            if (mm < minMm) minMm = mm
                            if (mm > maxMm) maxMm = mm
                        }

                        val intensity = if (mm == 0) 0 else {
                            val clamped = mm.coerceIn(250, 5_000)
                            (255f * (1f - (clamped - 250f) / 4_750f)).toInt().coerceIn(1, 255)
                        }
                        preview.put(intensity.toByte())
                    }
                }
                preview.position(0)

                val pose = FloatArray(7).also {
                    val t = cameraPose.translation
                    val q = cameraPose.rotationQuaternion
                    it[0] = t[0]; it[1] = t[1]; it[2] = t[2]
                    it[3] = q[0]; it[4] = q[1]; it[5] = q[2]; it[6] = q[3]
                }
                val sample = DepthSample(
                    timestampNanos = image.timestamp,
                    width = width,
                    height = height,
                    previewR8 = preview,
                    packedDepthMm = packed,
                    validPixels = valid,
                    minDepthMm = if (valid == 0) 0 else minMm,
                    maxDepthMm = if (valid == 0) 0 else maxMm,
                    pose = pose
                )

                if (allowKeyframe && sample.timestampNanos - lastKeyframeNanos >= keyframeIntervalNanos) {
                    if (keyframes.size >= maxKeyframes) keyframes.removeFirst()
                    keyframes.addLast(sample.copy(previewR8 = preview.duplicate().apply { position(0) }))
                    lastKeyframeNanos = sample.timestampNanos
                }
                stats = Stats(width, height, valid, sample.minDepthMm, sample.maxDepthMm, keyframes.size)
                sample
            }
        } catch (_: NotYetAvailableException) {
            null
        } catch (_: IllegalStateException) {
            null
        }
    }

    fun keyframeSnapshot(): List<DepthSample> = synchronized(keyframes) { keyframes.toList() }

    fun clear() {
        synchronized(keyframes) { keyframes.clear() }
        lastKeyframeNanos = 0L
        stats = Stats()
    }
}
