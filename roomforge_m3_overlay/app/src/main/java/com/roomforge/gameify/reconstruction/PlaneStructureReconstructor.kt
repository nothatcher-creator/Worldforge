package com.roomforge.gameify.reconstruction

import com.google.ar.core.Plane
import com.google.ar.core.Pose
import com.google.ar.core.Session
import com.google.ar.core.TrackingState

/**
 * Converts noisy/updating ARCore planes into a small semantic surface set.
 * M3 intentionally uses clean rectangles rather than raw scan triangles.
 */
class PlaneStructureReconstructor {
    enum class Kind { FLOOR, WALL }

    data class Surface(
        val id: String,
        val kind: Kind,
        val pose: Pose,
        val widthMeters: Float,
        val heightOrDepthMeters: Float,
        val confidence: Float
    )

    private data class Tracked(
        val id: String,
        val kind: Kind,
        var pose: Pose,
        var width: Float,
        var depth: Float,
        var observations: Int
    )

    private val tracked = LinkedHashMap<Plane, Tracked>()
    private var nextFloor = 1
    private var nextWall = 1

    fun update(session: Session): List<Surface> {
        val planes = session.getAllTrackables(Plane::class.java)
            .filter {
                it.trackingState == TrackingState.TRACKING &&
                    it.subsumedBy == null &&
                    it.extentX >= 0.15f && it.extentZ >= 0.15f
            }

        val lowestUpwardY = planes.asSequence()
            .filter { it.type == Plane.Type.HORIZONTAL_UPWARD_FACING }
            .map { it.centerPose.ty() }
            .minOrNull()

        val active = HashSet<Plane>()
        for (plane in planes) {
            val kind = when (plane.type) {
                Plane.Type.VERTICAL -> Kind.WALL
                Plane.Type.HORIZONTAL_UPWARD_FACING -> {
                    val floorY = lowestUpwardY ?: continue
                    if (plane.centerPose.ty() <= floorY + 0.22f) Kind.FLOOR else continue
                }
                else -> continue
            }
            active += plane
            val old = tracked[plane]
            if (old == null || old.kind != kind) {
                val id = when (kind) {
                    Kind.FLOOR -> "Floor_%03d".format(nextFloor++)
                    Kind.WALL -> "Wall_%03d".format(nextWall++)
                }
                tracked[plane] = Tracked(id, kind, plane.centerPose, plane.extentX, plane.extentZ, 1)
            } else {
                old.pose = plane.centerPose
                old.width = old.width * 0.65f + plane.extentX * 0.35f
                old.depth = old.depth * 0.65f + plane.extentZ * 0.35f
                old.observations++
            }
        }

        tracked.keys.removeAll { it !in active || it.trackingState == TrackingState.STOPPED || it.subsumedBy != null }
        return tracked.values.map {
            Surface(
                id = it.id,
                kind = it.kind,
                pose = it.pose,
                widthMeters = it.width,
                heightOrDepthMeters = it.depth,
                confidence = (it.observations / 20f).coerceIn(0.15f, 1f)
            )
        }
    }

    fun clear() {
        tracked.clear()
        nextFloor = 1
        nextWall = 1
    }
}
