package com.example.clipboardviewer

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.RecyclerView

/**
 * 列表左右滑动的公共实现（主界面与垃圾箱界面共用）。
 *
 * 统一交互：
 *  - 左滑：右侧露出红色背景 + [leftLabel]，滑过阈值触发 [onLeft]；
 *  - 右滑：左侧露出绿色背景 + [rightLabel]，滑过阈值触发 [onRight]。
 *
 * 浅色 = 还没滑够（松手不执行）；深色 = 已达阈值（松手即执行）。
 * 只允许「条目行」滑动，标题行（Row.Header）不可滑。
 */
object SwipeUi {

    // 滑过条目宽度的该比例即可触发（视觉变色点与触发点一致）。
    private const val SWIPE_THRESHOLD = 0.4f

    /**
     * 给 [recyclerView] 挂上左右滑动手势。
     *
     * @param leftLabel  左滑时右侧显示的文字（如「删除」「彻底删除」）。
     * @param rightLabel 右滑时左侧显示的文字（如「延后3天」）。
     * @param onLeft     左滑触发，回调被滑动的条目行。
     * @param onRight    右滑触发，回调被滑动的条目行。
     */
    fun attach(
        recyclerView: RecyclerView,
        adapter: FavAdapter,
        leftLabel: String,
        rightLabel: String,
        onLeft: (Row.Item) -> Unit,
        onRight: (Row.Item) -> Unit,
    ) {
        val redLight = Paint().apply { color = Color.parseColor("#EF9A9A") }    // 左滑（未到阈值）
        val redStrong = Paint().apply { color = Color.parseColor("#F44336") }   // 左滑（已到阈值）
        val greenLight = Paint().apply { color = Color.parseColor("#A5D6A7") }  // 右滑（未到阈值）
        val greenStrong = Paint().apply { color = Color.parseColor("#4CAF50") } // 右滑（已到阈值）
        val rightTextPaint = Paint().apply {   // 左滑文字（右对齐）
            color = Color.WHITE
            isAntiAlias = true
            textAlign = Paint.Align.RIGHT
            textSize = 44f
        }
        val leftTextPaint = Paint().apply {    // 右滑文字（左对齐）
            color = Color.WHITE
            isAntiAlias = true
            textAlign = Paint.Align.LEFT
            textSize = 44f
        }

        val callback = object :
            ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT) {
            override fun onMove(
                rv: RecyclerView,
                vh: RecyclerView.ViewHolder,
                target: RecyclerView.ViewHolder
            ): Boolean = false

            // 只允许「条目行」滑动，标题行不可滑
            override fun getSwipeDirs(rv: RecyclerView, vh: RecyclerView.ViewHolder): Int {
                val pos = vh.bindingAdapterPosition
                return if (pos != RecyclerView.NO_POSITION && adapter.itemAt(pos) != null)
                    ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT else 0
            }

            override fun getSwipeThreshold(vh: RecyclerView.ViewHolder): Float = SWIPE_THRESHOLD

            override fun onSwiped(vh: RecyclerView.ViewHolder, direction: Int) {
                val pos = vh.bindingAdapterPosition
                val item = if (pos != RecyclerView.NO_POSITION) adapter.itemAt(pos) else null
                // 先把该行恢复显示（操作完成后会整体刷新列表；失败则保留该行）
                if (pos != RecyclerView.NO_POSITION) adapter.notifyItemChanged(pos)
                if (item == null) return
                if (direction == ItemTouchHelper.RIGHT) onRight(item) else onLeft(item)
            }

            override fun onChildDraw(
                c: Canvas,
                rv: RecyclerView,
                vh: RecyclerView.ViewHolder,
                dX: Float,
                dY: Float,
                actionState: Int,
                isCurrentlyActive: Boolean
            ) {
                if (actionState == ItemTouchHelper.ACTION_STATE_SWIPE) {
                    val v = vh.itemView
                    // 是否已滑过触发阈值（达到则用深色，提示松手即执行）
                    val reached = v.width > 0 && Math.abs(dX) >= v.width * SWIPE_THRESHOLD
                    if (dX < 0) {
                        // 左滑：右侧背景 + leftLabel
                        c.drawRect(
                            v.right + dX, v.top.toFloat(), v.right.toFloat(), v.bottom.toFloat(),
                            if (reached) redStrong else redLight
                        )
                        val y = v.top + (v.height + rightTextPaint.textSize) / 2f
                        c.drawText(leftLabel, v.right - 30f, y, rightTextPaint)
                    } else if (dX > 0) {
                        // 右滑：左侧背景 + rightLabel
                        c.drawRect(
                            v.left.toFloat(), v.top.toFloat(), v.left + dX, v.bottom.toFloat(),
                            if (reached) greenStrong else greenLight
                        )
                        val y = v.top + (v.height + leftTextPaint.textSize) / 2f
                        c.drawText(rightLabel, v.left + 30f, y, leftTextPaint)
                    }
                }
                super.onChildDraw(c, rv, vh, dX, dY, actionState, isCurrentlyActive)
            }
        }
        ItemTouchHelper(callback).attachToRecyclerView(recyclerView)
    }
}
