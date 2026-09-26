package com.roomforge.gameify.render

import android.opengl.GLES30
import android.opengl.Matrix
import com.roomforge.gameify.reconstruction.PlaneStructureReconstructor
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

class StructureRenderer {
    private var program = 0
    private var positionLocation = -1
    private var mvpLocation = -1
    private var colorLocation = -1
    private val vertices = FloatArray(12)
    private val buffer: FloatBuffer = ByteBuffer.allocateDirect(vertices.size * 4)
        .order(ByteOrder.nativeOrder()).asFloatBuffer()
    private val model = FloatArray(16)
    private val viewModel = FloatArray(16)
    private val mvp = FloatArray(16)

    fun createOnGlThread() {
        program = GlUtil.createProgram(VERTEX, FRAGMENT)
        positionLocation = GLES30.glGetAttribLocation(program, "a_Position")
        mvpLocation = GLES30.glGetUniformLocation(program, "u_Mvp")
        colorLocation = GLES30.glGetUniformLocation(program, "u_Color")
    }

    fun draw(surfaces: List<PlaneStructureReconstructor.Surface>, view: FloatArray, projection: FloatArray) {
        if (surfaces.isEmpty()) return
        GLES30.glEnable(GLES30.GL_DEPTH_TEST)
        GLES30.glDepthMask(true)
        GLES30.glDisable(GLES30.GL_CULL_FACE)
        GLES30.glEnable(GLES30.GL_BLEND)
        GLES30.glBlendFunc(GLES30.GL_SRC_ALPHA, GLES30.GL_ONE_MINUS_SRC_ALPHA)
        GLES30.glUseProgram(program)
        GLES30.glEnableVertexAttribArray(positionLocation)

        for (surface in surfaces) {
            val halfX = surface.widthMeters * 0.5f
            val halfZ = surface.heightOrDepthMeters * 0.5f
            val v = floatArrayOf(
                -halfX, 0f, -halfZ,
                 halfX, 0f, -halfZ,
                -halfX, 0f,  halfZ,
                 halfX, 0f,  halfZ
            )
            buffer.position(0)
            buffer.put(v)
            buffer.position(0)
            GLES30.glVertexAttribPointer(positionLocation, 3, GLES30.GL_FLOAT, false, 0, buffer)

            surface.pose.toMatrix(model, 0)
            Matrix.multiplyMM(viewModel, 0, view, 0, model, 0)
            Matrix.multiplyMM(mvp, 0, projection, 0, viewModel, 0)
            GLES30.glUniformMatrix4fv(mvpLocation, 1, false, mvp, 0)
            val alpha = 0.24f + surface.confidence * 0.28f
            when (surface.kind) {
                PlaneStructureReconstructor.Kind.FLOOR -> GLES30.glUniform4f(colorLocation, 0.38f, 0.70f, 0.54f, alpha)
                PlaneStructureReconstructor.Kind.WALL -> GLES30.glUniform4f(colorLocation, 0.75f, 0.88f, 0.96f, alpha)
            }
            GLES30.glDrawArrays(GLES30.GL_TRIANGLE_STRIP, 0, 4)
        }

        GLES30.glDisableVertexAttribArray(positionLocation)
        GLES30.glDisable(GLES30.GL_BLEND)
    }

    companion object {
        private const val VERTEX = """
            #version 300 es
            in vec3 a_Position;
            uniform mat4 u_Mvp;
            void main() { gl_Position = u_Mvp * vec4(a_Position, 1.0); }
        """
        private const val FRAGMENT = """
            #version 300 es
            precision mediump float;
            uniform vec4 u_Color;
            out vec4 outColor;
            void main() { outColor = u_Color; }
        """
    }
}
