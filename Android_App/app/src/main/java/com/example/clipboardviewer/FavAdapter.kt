package com.example.clipboardviewer

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/** 列表行：收藏夹标题行 或 收藏条目行。 */
sealed class Row {
    data class Header(val title: String) : Row()
    data class Item(val id: Int, val text: String, val description: String) : Row()
}

/** 把收藏夹结构扁平化成带分组标题的行列表。 */
fun List<Folder>.toRows(): List<Row> {
    val rows = mutableListOf<Row>()
    for (folder in this) {
        rows.add(Row.Header("${folder.name}  (${folder.items.size})"))
        for (item in folder.items) {
            rows.add(Row.Item(item.id, item.text, item.description))
        }
    }
    return rows
}

/**
 * @param onItemLongClick 长按某条目时回调（用于弹出删除等操作）。
 */
class FavAdapter(
    private val onItemLongClick: (Row.Item) -> Unit
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    private val rows = mutableListOf<Row>()

    fun submit(newRows: List<Row>) {
        rows.clear()
        rows.addAll(newRows)
        notifyDataSetChanged()
    }

    override fun getItemViewType(position: Int): Int =
        if (rows[position] is Row.Header) TYPE_HEADER else TYPE_ITEM

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return if (viewType == TYPE_HEADER) {
            HeaderVH(inflater.inflate(R.layout.item_header, parent, false))
        } else {
            ItemVH(inflater.inflate(R.layout.item_fav, parent, false))
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val row = rows[position]) {
            is Row.Header -> (holder as HeaderVH).bind(row)
            is Row.Item -> {
                (holder as ItemVH).bind(row)
                holder.itemView.setOnLongClickListener {
                    onItemLongClick(row)
                    true
                }
            }
        }
    }

    override fun getItemCount(): Int = rows.size

    private class HeaderVH(view: View) : RecyclerView.ViewHolder(view) {
        private val text: TextView = view.findViewById(R.id.headerText)
        fun bind(row: Row.Header) {
            text.text = row.title
        }
    }

    private class ItemVH(view: View) : RecyclerView.ViewHolder(view) {
        private val text: TextView = view.findViewById(R.id.itemText)
        private val desc: TextView = view.findViewById(R.id.itemDesc)
        fun bind(row: Row.Item) {
            text.text = row.text
            if (row.description.isBlank()) {
                desc.visibility = View.GONE
            } else {
                desc.visibility = View.VISIBLE
                desc.text = row.description
            }
        }
    }

    companion object {
        private const val TYPE_HEADER = 0
        private const val TYPE_ITEM = 1
    }
}
