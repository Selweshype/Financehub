<x-app-layout>
    <x-slot name="header">
        <div class="flex justify-between items-center">
            <h2 class="font-semibold text-xl text-gray-800 leading-tight">Budgets</h2>
            <a href="{{ route('budgets.create') }}"
               class="inline-flex items-center px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700">
                + Add Budget
            </a>
        </div>
    </x-slot>

    <div class="py-8">
        <div class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">

            @if (session('success'))
                <div class="px-4 py-3 bg-green-100 text-green-800 rounded-md text-sm">{{ session('success') }}</div>
            @endif

            {{-- Month navigation --}}
            <div class="flex items-center justify-center gap-6">
                <a href="{{ route('budgets.index', ['month' => $prevMonth->month, 'year' => $prevMonth->year]) }}"
                   class="text-gray-500 hover:text-gray-800 text-lg">&#8592;</a>
                <span class="font-semibold text-gray-800 text-lg">
                    {{ \Carbon\Carbon::createFromDate($year, $month, 1)->format('F Y') }}
                </span>
                <a href="{{ route('budgets.index', ['month' => $nextMonth->month, 'year' => $nextMonth->year]) }}"
                   class="text-gray-500 hover:text-gray-800 text-lg">&#8594;</a>
            </div>

            @if ($budgets->isEmpty())
                <div class="bg-white rounded-lg shadow p-10 text-center text-gray-500">
                    <p class="mb-2">No budgets for this month.</p>
                    <a href="{{ route('budgets.create') }}" class="text-indigo-600 hover:underline">Create one</a>
                </div>
            @else
                <div class="bg-white rounded-lg shadow divide-y divide-gray-100">
                    @foreach ($budgets as $item)
                        @php
                            $pct   = $item['percentage'];
                            $color = $pct >= 100 ? 'bg-red-500' : ($pct >= 75 ? 'bg-amber-400' : 'bg-green-500');
                        @endphp
                        <div class="px-6 py-4 flex items-center gap-4">
                            <div class="flex-1 min-w-0">
                                <div class="flex justify-between items-center mb-1">
                                    <span class="font-medium text-gray-800">
                                        {{ $item['budget']->category->icon }} {{ $item['budget']->category->name }}
                                    </span>
                                    <span class="text-sm text-gray-600 ml-2 whitespace-nowrap">
                                        €{{ number_format($item['spent'], 2) }}
                                        <span class="text-gray-400">/ €{{ number_format($item['budget']->amount, 2) }}</span>
                                        <span class="ml-2 font-semibold {{ $pct >= 100 ? 'text-red-600' : ($pct >= 75 ? 'text-amber-600' : 'text-green-600') }}">
                                            {{ $pct }}%
                                        </span>
                                    </span>
                                </div>
                                <div class="w-full bg-gray-200 rounded-full h-2.5">
                                    <div class="{{ $color }} h-2.5 rounded-full transition-all"
                                         style="width: {{ $pct }}%"></div>
                                </div>
                            </div>
                            <form action="{{ route('budgets.destroy', $item['budget']) }}" method="POST"
                                  onsubmit="return confirm('Delete this budget?')">
                                @csrf @method('DELETE')
                                <button type="submit"
                                        class="text-red-400 hover:text-red-600 text-xs whitespace-nowrap">Delete</button>
                            </form>
                        </div>
                    @endforeach
                </div>
            @endif

        </div>
    </div>
</x-app-layout>
