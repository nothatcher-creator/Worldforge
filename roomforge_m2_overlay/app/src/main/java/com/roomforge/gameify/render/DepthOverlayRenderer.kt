package com.roomforge.gameify.render

import android.opengl.GLES30
import com.google.ar.core.Coordinates2d
import com.google.ar.core.Frame
import com.roomforge.gameify.depth.DepthEngine
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

class DepthOverlayRenderer {
    private var textureId = -1
    private var program = 0
    private var positionLocation = -1
    private var texCoordLocation = -1
    private var textureLocation = -1
    private var alphaLocation = -1
    private var allocatedWidth = 0
    private var allocatedHeight = 0

    private val quadCoords = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)
    private val transformedTexCoords = FloatArray(8)
    private val quadBuffer = floatBuffer(quadCoords)
    private val texBuffer = floatBuffer(FloatArray(8))

    fun createOnGlThread() {
        val textures = IntArray(1)
        GLES30.glGenTextures(1, textures, 0)
        textureId = textures[0]
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, textureId)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MIN_FILTER, GLES30.GL_LINEAR)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MAG_FILTER, GLES30.GL_LINEAR)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_S, GLES30.GL_CLAMP_TO_EDGE)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_T, GLES30.GL_CLAMP_TO_EDGE)
        program = GlUtil.createProgram(VERTEX, FRAGMENT)
        positionLocation = GLES30.glGetAttribLocation(program, "a_Position")
        texCoordLocation = GLES30.glGetAttribLocation(program, "a_TexCoord")
        textureLocation = GLES30.glGetUniformLocation(program, "u_Depth")
        alphaLocation = GLES30.glGetUniformLocation(program, "u_Alpha")
    }

    fun draw(frame: Frame, sample: DepthEngine.DepthSample, alpha: Float = 0.68f) {
        frame.transformCoordinates2d(
            Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES,
            quadCoords,
            Coordinates2d.IMAGE_NORMALIZED,
            transformedTexCoords
        )
        texBuffer.position(0)
        texBuffer.put(transformedTexCoords)
        texBuffer.position(0)

        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, textureId)
        sample.previewR8.position(0)
        if (sample.width != allocatedWidth || sample.height != allocatedHeight) {
            GLES30.glTexImage2D(
                GLES30.GL_TEXTURE_2D, 0, GLES30.GL_R8,
                sample.width, sample.height, 0,
                GLES30.GL_RED, GLES30.GL_UNSIGNED_BYTE, sample.previewR8
            )
            allocatedWidth = sample.width
            allocatedHeight = sample.height
        } else {
            GLES30.glTexSubImage2D(
                GLES30.GL_TEXTURE_2D, 0, 0, 0,
                sample.width, sample.height,
                GLES30.GL_RED, GLES30.GL_UNSIGNED_BYTE, sample.previewR8
            )
        }

        GLES30.glDisable(GLES30.GL_DEPTH_TEST)
        GLES30.glEnable(GLES30.GL_BLEND)
        GLES30.glBlendFunc(GLES30.GL_SRC_ALPHA, GLES30.GL_ONE_MINUS_SRC_ALPHA)
        GLES30.glDepthMask(false)
        GLES30.glUseProgram(program)
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0)
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, textureId)
        GLES30.glUniform1i(textureLocation, 0)
        GLES30.glUniform1f(alphaLocation, alpha)

        quadBuffer.position(0)
        GLES30.glEnableVertexAttribArray(positionLocation)
        GLES30.glVertexAttribPointer(positionLocation, 2, GLES30.GL_FLOAT, false, 0, quadBuffer)
        texBuffer.position(0)
        GLES30.glEnableVertexAttribArray(texCoordLocation)
        GLES30.glVertexAttribPointer(texCoordLocation, 2, GLES30.GL_FLOAT, false, 0, texBuffer)
        GLES30.glDrawArrays(GLES30.GL_TRIANGLE_STRIP, 0, 4)
        GLES30.glDisableVertexAttribArray(positionLocation)
        GLES30.glDisableVertexAttribArray(texCoordLocation)
        GLES30.glDepthMask(true)
        GLES30.glDisable(GLES30.GL_BLEND)
    }

    private fun floatBuffer(values: FloatArray): FloatBuffer =
        ByteBuffer.allocateDirect(values.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer().apply {
            put(values); position(0)
        }

    companion object {
        private const val VERTEX = """
            #version 300 es
            in vec2 a_Position;
            in vec2 a_TexCoord;
            out vec2 v_TexCoord;
            void main() {
                gl_Position = vec4(a_Position, 0.0, 1.0);
                v_TexCoord = a_TexCoord;
            }
        """
        private const val FRAGMENT = """
            #version 300 es
            precision mediump float;
            uniform sampler2D u_Depth;
            uniform float u_Alpha;
            in vec2 v_TexCoord;
            out vec4 outColor;
            void main() {
                float d = texture(u_Depth, v_TexCoord).r;
                if (d <= 0.002) discard;
                vec3 nearColor = vec3(1.0, 0.18, 0.08);
                vec3 midColor = vec3(1.0, 0.88, 0.10);
                vec3 farColor = vec3(0.10, 0.70, 1.0);
                vec3 c = d > 0.5
                    ? mix(midColor, nearColor, (d - 0.5) * 2.0)
                    : mix(farColor, midColor, d * 2.0);
                outColor = vec4(c, u_Alpha);
            }
        """
    }
}
